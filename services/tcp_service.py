"""Odoo transaction boundary. TCP connections belong to the bridge."""
import base64
import ipaddress
import secrets
import time
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from ..core.telemetry import decode_binary, decode_json, envelope, timestamp

class GatewayNotRegistered(RuntimeError):
    pass

class TCPIngestService:
    def __init__(self, dbname, config=None):
        self.dbname = dbname

    @staticmethod
    def _parse_reported_at(value):
        return timestamp(value)

    @staticmethod
    def _configure_ingest_cursor(cr):
        cr.connection.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)

    def _ensure_sensor(self, env, gateway, node_id, probe_code):
        node_id, probe_code = node_id.strip().upper(), probe_code.strip().upper()
        model = env["iot.th.sensor"].sudo().with_context(active_test=False)
        domain = [("gateway_id", "=", gateway.id), ("node_id", "=", node_id), ("probe_code", "=", probe_code)]
        sensor = model.search(domain, limit=1)
        if sensor and not sensor.active:
            raise ValueError("probe identity is archived")
        if not sensor:
            sensor = model.create({"name": f"{node_id}-{probe_code.lower()}", "gateway_id": gateway.id,
                                   "node_id": node_id, "probe_code": probe_code, "company_id": gateway.company_id.id,
                                   "stats_window_hours": gateway.statistics_window_hours or 24})
        return sensor

    def ingest(self, data, binary=False):
        event_id, received_at, digest = envelope(data)
        if binary:
            if not isinstance(data.get("source_ip"), str):
                raise ValueError("binary gateway source address is required")
            source_address = str(ipaddress.ip_address(data["source_ip"]))
            readings = decode_binary(base64.b64decode(data.get("frame_b64", ""), validate=True))
            at, payload = received_at, {}
        else:
            payload, at, readings = decode_json(data.get("payload_text", ""), received_at)
        registry = Registry(self.dbname)
        for attempt in range(3):
            try:
                with registry.cursor() as cr:
                    self._configure_ingest_cursor(cr)
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    gateways = env["iot.th.gateway"].sudo()
                    identity = [("source_address", "=", source_address)] if binary else [("serial", "=", payload.get("gateway_serial"))]
                    gateway = gateways.search(identity + [("active", "=", True), ("company_id", "!=", False)], limit=1)
                    if not gateway:
                        raise GatewayNotRegistered("Register the gateway and its company before ingesting")
                    if not binary and (not gateway.tcp_token or not secrets.compare_digest(gateway.tcp_token, str(payload.get("token") or ""))):
                        raise ValueError("gateway authentication failed")
                    if not env["iot.ingest.event"]._claim(event_id, "th.binary" if binary else "th.json", digest, received_at):
                        return {"ok": True, "event_id": event_id, "duplicate": True}
                    # Serialize discovery per registered gateway, not across companies.
                    cr.execute("SELECT id FROM iot_th_gateway WHERE id = %s FOR UPDATE", [gateway.id])
                    gateway.invalidate_recordset()
                    if not gateway.last_seen or gateway.last_seen < received_at:
                        gateway.last_seen = received_at
                    values, sensors = [], []
                    for value in readings:
                        sensor = self._ensure_sensor(env, gateway, value.node, value.channel)
                        if sensor.company_id != gateway.company_id:
                            raise ValueError("probe and gateway company mismatch")
                        sensors.append((sensor, value))
                        values.append({"sensor_id": sensor.id, "gateway_id": gateway.id, "event_id": event_id,
                                       "reported_at": at, "received_at": received_at,
                                       "temperature": value.temperature, "humidity": value.humidity})
                    env["iot.th.reading"].create(values)
                    for sensor, value in sensors:
                        sensor._apply_reading(value.temperature, value.humidity, at, battery_voltage=value.battery)
                    cr.commit()
                    return {"ok": True, "event_id": event_id, "samples": len(values)}
            except Exception as exc:
                if getattr(exc, "pgcode", None) not in ("40001", "40P01") or attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))

def ensure_running(env):
    """Old hook intentionally does not open an Odoo socket."""
    return None

def process_ingest_payload(env, data, binary=False):
    return TCPIngestService(env.cr.dbname).ingest(data, binary=binary)
