import json
import logging
import socketserver
import threading
from datetime import datetime

from odoo import SUPERUSER_ID, api, fields
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

_instances = {}
_instances_lock = threading.Lock()


class _GatewayTCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        service = getattr(self.server, "service", None)
        if not service:
            return

        buffer = bytearray()
        source_ip = self.client_address[0] if self.client_address else None
        source_port = self.client_address[1] if self.client_address else None
        while True:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            service._create_raw_packet(
                "tcp_chunk",
                chunk.hex().upper(),
                source_ip=source_ip,
                source_port=source_port,
            )
            buffer.extend(chunk)
            service.process_buffer(buffer, source_ip=source_ip, source_port=source_port)


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TCPIngestService:
    def __init__(self, dbname, config):
        self.dbname = dbname
        self.config = config
        self._server = None
        self._thread = None
        self._started = False
        self._lock = threading.Lock()

    def _parse_reported_at(self, value):
        if not value:
            return fields.Datetime.now()
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return fields.Datetime.now()

    def _ensure_gateway(self, env, serial):
        gateway_model = env["iot.th.gateway"].sudo()
        gateway = gateway_model.search([("serial", "=", serial)], limit=1)
        if not gateway:
            gateway = gateway_model.create(
                {
                    "name": serial,
                    "serial": serial,
                }
            )
        return gateway

    def _ensure_sensor(self, env, gateway, node_id, probe_code):
        sensor_model = env["iot.th.sensor"].sudo()
        sensor = sensor_model.search(
            [("node_id", "=", node_id), ("probe_code", "=", probe_code)],
            limit=1,
        )
        if not sensor:
            sensor = sensor_model.create(
                {
                    "gateway_id": gateway.id,
                    "node_id": node_id,
                    "probe_code": probe_code,
                    "name": f"{gateway.serial}-{node_id}-{probe_code}",
                    "stats_window_hours": gateway.statistics_window_hours or 24,
                }
            )
        elif sensor.gateway_id != gateway:
            sensor.gateway_id = gateway.id
        return sensor

    def _ingest_measurements(
        self,
        serial,
        reported_at,
        measurements,
        raw_payload,
        token=None,
        extra_gateway_vals=None,
        node_id=None,
    ):
        registry = Registry(self.dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            reading_model = env["iot.th.reading"].sudo()

            gateway = self._ensure_gateway(env, serial)
            if extra_gateway_vals:
                gateway.sudo().write(extra_gateway_vals)

            if gateway.tcp_token and token is not None and token != gateway.tcp_token:
                _logger.warning("TH payload token mismatch for gateway %s", serial)
                cr.commit()
                return

            gateway.last_seen = reported_at

            for m in measurements:
                probe_code = m.get("probe_code")
                if not probe_code:
                    continue
                temperature = m.get("temperature")
                humidity = m.get("humidity")
                battery_voltage = m.get("battery_voltage")
                if temperature is None or humidity is None:
                    continue

                sensor_node_id = (m.get("node_id") or node_id or "").strip().lower()
                if not sensor_node_id:
                    sensor_node_id = "unknown"

                sensor = self._ensure_sensor(env, gateway, sensor_node_id, probe_code)
                reading_model.create(
                    {
                        "sensor_id": sensor.id,
                        "gateway_id": gateway.id,
                        "reported_at": reported_at,
                        "temperature": float(temperature),
                        "humidity": float(humidity),
                        "raw_payload": raw_payload,
                    }
                )
                sensor.apply_reading(float(temperature), float(humidity), reported_at, battery_voltage=battery_voltage)

            cr.commit()

    def _create_raw_packet(
        self,
        protocol,
        raw_payload,
        source_ip=None,
        source_port=None,
        serial_hint=None,
        node_id=None,
    ):
        registry = Registry(self.dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            raw_model = env["iot.th.raw.packet"].sudo()
            gateway = False
            if serial_hint:
                gateway = env["iot.th.gateway"].sudo().search([("serial", "=", serial_hint)], limit=1)

            rec = raw_model.create(
                {
                    "gateway_id": gateway.id if gateway else False,
                    "source_ip": source_ip,
                    "source_port": source_port,
                    "protocol": protocol,
                    "node_id": node_id,
                    "serial_hint": serial_hint,
                    "raw_payload": raw_payload,
                    "parse_ok": False,
                }
            )
            cr.commit()
            return rec.id

    def _update_raw_packet_parse_status(self, packet_id, parse_ok, parse_error=None, serial_hint=None, node_id=None):
        if not packet_id:
            return
        registry = Registry(self.dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            vals = {"parse_ok": bool(parse_ok), "parse_error": parse_error or False}
            if serial_hint:
                gateway = env["iot.th.gateway"].sudo().search([("serial", "=", serial_hint)], limit=1)
                if gateway:
                    vals["gateway_id"] = gateway.id
                    vals["serial_hint"] = serial_hint
            if node_id:
                vals["node_id"] = node_id
            env["iot.th.raw.packet"].sudo().browse(packet_id).write(vals)
            cr.commit()

    def process_json_line(self, payload_text, source_ip=None, source_port=None):
        packet_id = self._create_raw_packet(
            "tcp_json",
            payload_text,
            source_ip=source_ip,
            source_port=source_port,
        )
        try:
            payload = json.loads(payload_text)
        except Exception:
            _logger.warning("Invalid TH JSON payload: %s", payload_text)
            self._update_raw_packet_parse_status(packet_id, False, parse_error="Invalid JSON payload")
            return

        serial = payload.get("gateway_serial") or source_ip
        if not serial:
            _logger.warning("TH JSON payload missing gateway_serial: %s", payload_text)
            self._update_raw_packet_parse_status(packet_id, False, parse_error="Missing gateway_serial")
            return
        node_id = str(
            payload.get("node_id")
            or payload.get("nodeId")
            or payload.get("gateway_node_id")
            or ""
        ).strip().lower() or None

        reported_at = self._parse_reported_at(payload.get("reported_at"))
        token = payload.get("token")

        probes = payload.get("probes") or []
        if not probes and payload.get("probe_code"):
            probes = [payload]

        measurements = []
        for probe in probes:
            code = str(probe.get("probe_code") or "").strip()
            if not code:
                continue
            try:
                t = float(probe.get("temperature"))
                h = float(probe.get("humidity"))
            except Exception:
                continue
            bv = probe.get("battery_voltage", payload.get("battery_voltage"))
            try:
                bv = float(bv) if bv is not None else None
            except Exception:
                bv = None
            measurements.append({"probe_code": code, "node_id": node_id, "temperature": t, "humidity": h, "battery_voltage": bv})

        self._ingest_measurements(serial, reported_at, measurements, payload_text, token=token, node_id=node_id)
        self._update_raw_packet_parse_status(packet_id, True, serial_hint=serial, node_id=node_id)

    def process_binary_frame(self, frame, source_ip=None, source_port=None):
        raw_payload = frame.hex().upper()
        node_id = f"{((frame[3] << 8) | frame[4]):04x}" if len(frame) >= 5 else None
        packet_id = self._create_raw_packet(
            "tcp_binary",
            raw_payload,
            source_ip=source_ip,
            source_port=source_port,
            node_id=node_id,
        )
        try:
        # Format per gateway spec:
        # BYTE0=0xFA BYTE1=0xCE BYTE2=control BYTE3-4=sender addr BYTE5=device info BYTE6=seq BYTE7=data count(16-bit words)
        # BYTE8.. data area, each word is 16-bit big-endian; 1 channel => temp(signed*10), humidity(unsigned)
        # Last byte checksum = sum(BYTE0..BYTE(n-1)) & 0xFF
            if len(frame) < 9:
                self._update_raw_packet_parse_status(packet_id, False, parse_error="Frame too short")
                return
            if frame[0] != 0xFA or frame[1] != 0xCE:
                self._update_raw_packet_parse_status(packet_id, False, parse_error="Invalid frame header")
                return

            expected_checksum = sum(frame[:-1]) & 0xFF
            if expected_checksum != frame[-1]:
                _logger.warning("TH binary checksum mismatch, drop frame: got=%s expected=%s", frame[-1], expected_checksum)
                self._update_raw_packet_parse_status(packet_id, False, parse_error="Checksum mismatch")
                return

            data_count = frame[7]
            if data_count < 2:
                self._update_raw_packet_parse_status(packet_id, False, parse_error="Invalid data_count")
                return

            data_start = 8
            data_end = len(frame) - 1
            data = frame[data_start:data_end]

            if len(data) != data_count * 2:
                _logger.warning("TH binary length mismatch: data_count=%s bytes=%s", data_count, len(data))
                self._update_raw_packet_parse_status(packet_id, False, parse_error="Data length mismatch")
                return

            addr = (frame[3] << 8) | frame[4]
            serial = source_ip or "UNKNOWN_GATEWAY"
            voltage = frame[5] / 10.0

            measurements = []
            # Multi-channel support: each channel uses two words: temp, humidity
            pair_count = data_count // 2
            for i in range(pair_count):
                off = i * 4
                temp_raw = int.from_bytes(data[off : off + 2], byteorder="big", signed=True)
                hum_raw = int.from_bytes(data[off + 2 : off + 4], byteorder="big", signed=False)

                measurements.append(
                    {
                        "probe_code": f"CH{i + 1:02d}",
                        "node_id": node_id,
                        "temperature": temp_raw / 10.0,
                        "humidity": float(hum_raw),
                        "battery_voltage": voltage,
                    }
                )

            extra_gateway_vals = {"name": f"Gateway {serial}", "sampling_interval_min": 1}
            reported_at = fields.Datetime.now()

            self._ingest_measurements(
                serial,
                reported_at,
                measurements,
                raw_payload,
                token=None,
                extra_gateway_vals=extra_gateway_vals,
                node_id=node_id,
            )
            self._update_raw_packet_parse_status(packet_id, True, serial_hint=serial, node_id=node_id)
        except Exception as exc:
            _logger.exception("TH binary frame processing failed")
            self._update_raw_packet_parse_status(packet_id, False, parse_error=f"Exception: {exc}")

    def process_buffer(self, buffer, source_ip=None, source_port=None):
        # Mixed protocol parser: legacy JSON lines + binary frames.
        while buffer:
            # JSON-line mode (legacy compatibility)
            if buffer[0] in (ord("{"), ord("[")):
                nl = buffer.find(b"\n")
                if nl < 0:
                    return
                line = bytes(buffer[:nl]).decode("utf-8", errors="ignore").strip()
                del buffer[: nl + 1]
                if line:
                    self.process_json_line(line, source_ip=source_ip, source_port=source_port)
                continue

            # Binary frame mode.
            idx = buffer.find(b"\xFA\xCE")
            if idx < 0:
                # Keep last byte in case it is partial header.
                unknown = bytes(buffer[:-1]) if len(buffer) > 1 else b""
                if unknown:
                    raw_payload = unknown.hex().upper()
                    self._create_raw_packet(
                        "tcp_unknown",
                        raw_payload,
                        source_ip=source_ip,
                        source_port=source_port,
                    )
                if len(buffer) > 1:
                    del buffer[:-1]
                return

            if idx > 0:
                unknown = bytes(buffer[:idx])
                if unknown:
                    self._create_raw_packet(
                        "tcp_unknown",
                        unknown.hex().upper(),
                        source_ip=source_ip,
                        source_port=source_port,
                    )
                del buffer[:idx]

            if len(buffer) < 9:
                return

            data_count = buffer[7]
            frame_len = 9 + data_count * 2
            if len(buffer) < frame_len:
                return

            frame = bytes(buffer[:frame_len])
            del buffer[:frame_len]
            self.process_binary_frame(frame, source_ip=source_ip, source_port=source_port)

    def start(self):
        with self._lock:
            if self._started:
                return True

            host = self.config.get("host")
            port = self.config.get("port")
            if not host or not port:
                return False

            try:
                self._server = _ThreadedTCPServer((host, port), _GatewayTCPHandler)
            except OSError as exc:
                _logger.warning("TH TCP service cannot bind %s:%s (%s)", host, port, exc)
                self._server = None
                self._thread = None
                self._started = False
                return False
            self._server.service = self
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._started = True
            _logger.info("TH TCP service started on %s:%s", host, port)
            return True

    def stop(self):
        with self._lock:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
            self._server = None
            self._thread = None
            self._started = False


def _load_config(env):
    icp = env["ir.config_parameter"].sudo()
    host = icp.get_param("iot_control_center.th_tcp_host")
    port_raw = icp.get_param("iot_control_center.th_tcp_port")

    if host in (False, None, "", "False", "false"):
        host = "0.0.0.0"
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 9910
    if port <= 0:
        port = 9910

    return {
        "host": host,
        "port": port,
    }


def ensure_running(env):
    dbname = env.cr.dbname
    config = _load_config(env)

    key = (dbname, config["host"], config["port"])
    with _instances_lock:
        current = _instances.get(dbname)
        if current and getattr(current, "config", {}) != config:
            current.stop()
            _instances.pop(dbname, None)
            current = None

        if not current:
            current = TCPIngestService(dbname, config)
            _instances[dbname] = current

    current.start()
    return current
