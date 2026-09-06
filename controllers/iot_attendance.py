import json
import logging
import ipaddress

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class IoTAttendanceController(http.Controller):
    def _plain_ok(self, body="OK", status=200):
        return request.make_response(
            body,
            status=status,
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
                # Some attendance terminals keep stale HTTP sessions and only recover after reboot.
                # Force short-lived responses so every heartbeat/data push uses a fresh connection.
                ("Connection", "close"),
                ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
                ("Pragma", "no-cache"),
            ],
        )

    def _read_payload(self):
        limit = 1024 * 1024
        if (request.httprequest.content_length or 0) > limit:
            raise ValueError("Attendance upload too large")
        request.httprequest.max_content_length = limit
        data = request.httprequest.get_data(cache=True)
        if len(data) > limit:
            raise ValueError("Attendance upload too large")
        if not data and request.httprequest.content_length:
            # Odoo may already have consumed a form-encoded body. Never ACK it
            # as an empty successful upload when no attendance was imported.
            raise ValueError("Attendance upload body unavailable; use text/plain")
        return data.decode("utf-8", errors="strict")

    def _touch_device(self, device, serial_number="", payload_text=""):
        if not device:
            return
        try:
            with request.env.cr.savepoint():
                now = fields.Datetime.now()
                values = {}
                # Throttle heartbeat writes to reduce contention under high request bursts.
                if not device.adms_last_seen_at or (now - device.adms_last_seen_at).total_seconds() >= 15:
                    values["adms_last_seen_at"] = now
                if serial_number and not device.serial_number:
                    values["serial_number"] = serial_number
                if values:
                    device.write(values)
        except Exception as exc:
            _logger.warning("IoT attendance device update skipped type=%s", type(exc).__name__)

    def _compact_query_params(self):
        keep_keys = ("SN", "sn", "table", "Table", "Stamp", "stamp", "OpStamp", "ErrorDelay")
        compact = {}
        for key in keep_keys:
            value = request.params.get(key)
            if value not in (None, "", False):
                compact[key] = value
        return compact

    def _source_ip_allowed(self, remote_ip):
        raw = (request.env["ir.config_parameter"].sudo().get_param("iot_control_center.attendance_allowed_ips") or "").strip()
        if not raw:
            return True
        try:
            source = ipaddress.ip_address(remote_ip)
        except Exception:
            return False
        for item in [part.strip() for part in raw.split(",") if part.strip()]:
            try:
                if "/" in item:
                    if source in ipaddress.ip_network(item, strict=False):
                        return True
                elif source == ipaddress.ip_address(item):
                    return True
            except Exception:
                _logger.warning("Invalid attendance allowed IP entry ignored: %s", item)
        return False

    def _create_request_log(
        self,
        endpoint,
        serial_number="",
        remote_ip="",
        payload_text="",
        device=None,
        status="received",
        note="",
        sample_seconds=0,
    ):
        try:
            with request.env.cr.savepoint():
                request_model = request.env["iot.attendance.request"].sudo()
                values = {
                    "endpoint": endpoint,
                    "method": request.httprequest.method,
                    "serial_number": serial_number or False,
                    "remote_ip": remote_ip or False,
                    "payload_text": False,
                    "status": status,
                    "note": note or False,
                    "device_id": device.id if device else False,
                    "query_params": json.dumps(self._compact_query_params(), ensure_ascii=True, sort_keys=True) or False,
                    "headers": False,
                }
                return request_model.create_sampled(values, sample_seconds=sample_seconds)
        except Exception as exc:
            # Never block attendance ingest because auxiliary request logging failed.
            _logger.warning("IoT attendance request log write skipped type=%s", type(exc).__name__)
            return False

    @http.route("/iot_attendance/push/<int:device_id>", type="http", auth="none", methods=["POST"], csrf=False, readonly=False)
    def device_push(self, device_id, **kwargs):
        token = (request.httprequest.headers.get("X-Attendance-Token") or "").strip()
        device = request.env["iot.attendance.device"].sudo().browse(device_id)
        if not device.exists():
            return request.make_json_response({"ok": False, "error": "device not found"}, status=404)
        if not device._validate_webhook_token(token):
            return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            payload = json.loads(self._read_payload() or "{}")
        except (ValueError, UnicodeError):
            return request.make_json_response({"ok": False, "error": "invalid or oversized payload"}, status=400)
        punches = payload.get("punches") if isinstance(payload, dict) else None
        if punches is None:
            punches = [payload]
        try:
            with request.env.cr.savepoint():
                created = device._ingest_webhook_payload(punches)
        except Exception:
            _logger.warning("Attendance webhook ingest failed for device id=%s", device.id)
            return request.make_json_response({"ok": False, "error": "attendance import failed"}, status=422)
        return request.make_json_response({"ok": True, "created": created})

    @http.route(["/getrequest", "/iclock", "/iclock/getrequest"], type="http", auth="none", methods=["GET", "POST"], csrf=False, readonly=False)
    def adms_getrequest(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        if not self._source_ip_allowed(remote_ip):
            return self._plain_ok("ERROR", status=403)
        payload_text = ""
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        request_model = request.env["iot.attendance.request"].sudo()
        log = self._create_request_log(
            request.httprequest.path,
            serial_number,
            remote_ip,
            payload_text,
            device if device else None,
            "matched" if device else "ignored",
            "Heartbeat / getrequest",
            sample_seconds=request_model._heartbeat_sample_seconds() if device else 0,
        )
        self._touch_device(device, serial_number, payload_text)
        if device and log and not log.device_id:
            log.device_id = device.id
        return self._plain_ok("OK")

    @http.route(["/cdata", "/iclock/cdata"], type="http", auth="none", methods=["GET", "POST"], csrf=False, readonly=False)
    def adms_cdata(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        table = (request.params.get("table") or request.params.get("Table") or "").strip()
        remote_ip = request.httprequest.remote_addr
        if not self._source_ip_allowed(remote_ip):
            return self._plain_ok("ERROR", status=403)
        if table.upper() not in ("", "ATTLOG"):
            return self._plain_ok()
        try:
            payload_text = self._read_payload()
        except (ValueError, UnicodeError):
            return self._plain_ok("ERROR", status=400)
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        log = self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", f"table={table or '-'}")
        if not device:
            return self._plain_ok("ERROR", status=403)
        self._touch_device(device, serial_number, payload_text)
        if payload_text.strip():
            try:
                with request.env.cr.savepoint():
                    created = device._ingest_adms_payload(payload_text=payload_text, table=table, serial_number=serial_number, remote_ip=remote_ip, query_params=request.params)
                if log:
                    log.write({"status": "parsed", "note": f"table={table or '-'} created={created}"})
            except Exception as exc:
                if log:
                    log.write({"status": "error", "note": "Attendance import failed; batch rolled back."})
                _logger.warning("IoT ADMS ingest failed for device id=%s type=%s", device.id, type(exc).__name__)
                return self._plain_ok("ERROR", status=500)
        else:
            if log:
                log.write({"note": f"table={table or '-'} empty payload"})
        return self._plain_ok("OK")

    @http.route(["/registry", "/iclock/registry"], type="http", auth="none", methods=["GET", "POST"], csrf=False, readonly=False)
    def adms_registry(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        if not self._source_ip_allowed(remote_ip):
            return self._plain_ok("ERROR", status=403)
        payload_text = ""
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", "Registry")
        self._touch_device(device, serial_number, payload_text)
        return self._plain_ok("OK")

    @http.route(["/devicecmd", "/iclock/devicecmd"], type="http", auth="none", methods=["GET", "POST"], csrf=False, readonly=False)
    def adms_devicecmd(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        if not self._source_ip_allowed(remote_ip):
            return self._plain_ok("ERROR", status=403)
        payload_text = ""
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", "Device command poll")
        self._touch_device(device, serial_number, payload_text)
        return self._plain_ok("OK")

    @http.route("/iclock/<path:subpath>", type="http", auth="none", methods=["GET", "POST"], csrf=False, readonly=False)
    def adms_catch_all(self, subpath=None, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        table = (request.params.get("table") or request.params.get("Table") or "").strip()
        remote_ip = request.httprequest.remote_addr
        if not self._source_ip_allowed(remote_ip):
            return self._plain_ok("ERROR", status=403)
        if table.upper() not in ("", "ATTLOG"):
            return self._plain_ok()
        try:
            payload_text = self._read_payload()
        except (ValueError, UnicodeError):
            return self._plain_ok("ERROR", status=400)
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        log = self._create_request_log(
            request.httprequest.path,
            serial_number,
            remote_ip,
            payload_text,
            device if device else None,
            "matched" if device else "ignored",
            f"Catch-all route table={table or '-'}",
        )
        self._touch_device(device, serial_number, payload_text)
        if device and payload_text.strip():
            try:
                with request.env.cr.savepoint():
                    created = device._ingest_adms_payload(
                        payload_text=payload_text, table=table, serial_number=serial_number,
                        remote_ip=remote_ip, query_params=request.params)
                if log:
                    log.write({"status": "parsed", "note": f"catch-all table={table or '-'} created={created}"})
            except Exception as exc:
                if log:
                    log.write({"status": "error", "note": "Attendance import failed; batch rolled back."})
                _logger.warning("IoT ADMS catch-all ingest failed type=%s", type(exc).__name__)
                return self._plain_ok("ERROR", status=500)
        elif not device and payload_text.strip():
            return self._plain_ok("ERROR", status=403)
        return self._plain_ok("OK")
