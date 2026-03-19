import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class IoTAttendanceController(http.Controller):
    def _plain_ok(self, body="OK"):
        return request.make_response(body, headers=[("Content-Type", "text/plain; charset=utf-8")])

    def _headers(self):
        return {key: value for key, value in request.httprequest.headers.items()}

    def _touch_device(self, device, serial_number="", payload_text=""):
        if not device:
            return
        try:
            now = fields.Datetime.now()
            values = {}
            # Throttle heartbeat writes to reduce transaction conflicts under high request bursts.
            if not device.adms_last_seen_at or (now - device.adms_last_seen_at).total_seconds() >= 15:
                values["adms_last_seen_at"] = now
            if payload_text and (not device.adms_last_payload or device.adms_last_payload[:10000] != payload_text[:10000]):
                values["adms_last_payload"] = payload_text[:10000]
            if serial_number and not device.serial_number:
                values["serial_number"] = serial_number
            if values:
                device.write(values)
        except Exception as exc:
            _logger.warning("IoT attendance device touch skipped due to DB conflict: %s", exc)

    def _compact_query_params(self):
        keep_keys = ("SN", "sn", "table", "Table", "Stamp", "stamp", "OpStamp", "ErrorDelay")
        compact = {}
        for key in keep_keys:
            value = request.params.get(key)
            if value not in (None, "", False):
                compact[key] = value
        return compact

    def _create_request_log(self, endpoint, serial_number="", remote_ip="", payload_text="", device=None, status="received", note=""):
        try:
            return request.env["iot.attendance.request"].sudo().create(
                {
                    "endpoint": endpoint,
                    "method": request.httprequest.method,
                    "serial_number": serial_number or False,
                    "remote_ip": remote_ip or False,
                    "payload_text": (payload_text or "")[:1000] or False,
                    "status": status,
                    "note": note or False,
                    "device_id": device.id if device else False,
                    "query_params": json.dumps(self._compact_query_params(), ensure_ascii=True, sort_keys=True) or False,
                    "headers": False,
                }
            )
        except Exception as exc:
            # Never block attendance ingest because of request-log write contention.
            _logger.warning("IoT attendance request log skipped due to DB conflict: %s", exc)
            return False

    @http.route("/iot_attendance/push/<int:device_id>", type="http", auth="none", methods=["POST"], csrf=False)
    def device_push(self, device_id, **kwargs):
        try:
            payload = json.loads((request.httprequest.data or b"{}").decode("utf-8"))
        except Exception:
            return request.make_json_response({"ok": False, "error": "invalid json"}, status=400)
        token = (request.httprequest.headers.get("X-Attendance-Token") or "").strip()
        device = request.env["iot.attendance.device"].sudo().browse(device_id)
        if not device.exists():
            return request.make_json_response({"ok": False, "error": "device not found"}, status=404)
        if not device._validate_webhook_token(token):
            return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
        punches = payload.get("punches") if isinstance(payload, dict) else None
        if punches is None:
            punches = [payload]
        created = device.ingest_webhook_payload(punches)
        return request.make_json_response({"ok": True, "created": created})

    @http.route(["/getrequest", "/iclock", "/iclock/getrequest"], type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def adms_getrequest(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        payload_text = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        log = self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", "Heartbeat / getrequest")
        self._touch_device(device, serial_number, payload_text)
        if device and log and not log.device_id:
            log.device_id = device.id
        return self._plain_ok("OK")

    @http.route(["/cdata", "/iclock/cdata"], type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def adms_cdata(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        table = (request.params.get("table") or request.params.get("Table") or "").strip()
        remote_ip = request.httprequest.remote_addr
        payload_text = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        log = self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", f"table={table or '-'}")
        if not device:
            return self._plain_ok("OK")
        self._touch_device(device, serial_number, payload_text)
        if payload_text.strip():
            try:
                created = device.ingest_adms_payload(payload_text=payload_text, table=table, serial_number=serial_number, remote_ip=remote_ip, query_params=request.params)
                if log:
                    log.write({"status": "parsed", "note": f"table={table or '-'} created={created}"})
            except Exception as exc:
                if log:
                    log.write({"status": "error", "note": str(exc)[:255]})
                _logger.exception("IoT ADMS ingest failed for device %s: %s", device.display_name, exc)
                return self._plain_ok("ERROR")
        else:
            if log:
                log.write({"note": f"table={table or '-'} empty payload"})
        return self._plain_ok("OK")

    @http.route(["/registry", "/iclock/registry"], type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def adms_registry(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        payload_text = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", "Registry")
        self._touch_device(device, serial_number, payload_text)
        return self._plain_ok("OK")

    @http.route(["/devicecmd", "/iclock/devicecmd"], type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def adms_devicecmd(self, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        remote_ip = request.httprequest.remote_addr
        payload_text = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        self._create_request_log(request.httprequest.path, serial_number, remote_ip, payload_text, device if device else None, "matched" if device else "ignored", "Device command poll")
        self._touch_device(device, serial_number, payload_text)
        return self._plain_ok("OK")

    @http.route("/iclock/<path:subpath>", type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def adms_catch_all(self, subpath=None, **kwargs):
        serial_number = (request.params.get("SN") or request.params.get("sn") or "").strip()
        table = (request.params.get("table") or request.params.get("Table") or "").strip()
        remote_ip = request.httprequest.remote_addr
        payload_text = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
        device = request.env["iot.attendance.device"].sudo()._find_adms_device(serial_number, remote_ip=remote_ip)
        if table.upper() == "ATTPHOTO":
            self._touch_device(device, serial_number, payload_text)
            return self._plain_ok("OK")
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
                created = device.ingest_adms_payload(
                    payload_text=payload_text,
                    table=table,
                    serial_number=serial_number,
                    remote_ip=remote_ip,
                    query_params=request.params,
                )
                if log:
                    log.write({"status": "parsed", "note": f"catch-all table={table or '-'} created={created}"})
            except Exception as exc:
                if log:
                    log.write({"status": "error", "note": str(exc)[:255]})
                _logger.exception("IoT ADMS catch-all ingest failed for %s: %s", request.httprequest.path, exc)
        return self._plain_ok("OK")
