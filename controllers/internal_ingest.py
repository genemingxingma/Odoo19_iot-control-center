import json
import logging
import secrets

from odoo import http
from odoo.http import request
from ..core.telemetry import MAX_BODY_BYTES, envelope
from ..services.tcp_service import GatewayNotRegistered, process_ingest_payload

_logger = logging.getLogger(__name__)

class IoTInternalIngestController(http.Controller):
    def _check_token(self):
        expected = request.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_token") or ""
        provided = request.httprequest.headers.get("X-IoT-Middleware-Token") or ""
        return bool(expected) and secrets.compare_digest(expected, provided)

    def _parse_json(self):
        length = request.httprequest.content_length
        if length and length > MAX_BODY_BYTES:
            raise ValueError("payload too large")
        raw = request.httprequest.stream.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError("payload too large")
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("object required")
        return data

    def _dispatch(self, route, handler, receipt=True):
        if not self._check_token():
            return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            data = self._parse_json()
            with request.env.cr.savepoint():
                if receipt:
                    event_id, received_at, digest = envelope(data)
                    if not request.env["iot.ingest.event"].sudo()._claim(event_id, route, digest, received_at):
                        return request.make_json_response({"ok": True, "event_id": event_id, "duplicate": True})
                result = handler(data)
            return request.make_json_response(result)
        except GatewayNotRegistered:
            return request.make_json_response({"ok": False, "error": "gateway registration required"}, status=503)
        except (ValueError, TypeError, KeyError, OverflowError):
            return request.make_json_response({"ok": False, "error": "invalid event"}, status=400)
        except Exception:
            _logger.exception("IoT event transaction failed on %s", route)
            return request.make_json_response({"ok": False, "error": "temporary ingest failure"}, status=503)

    @http.route("/iot_control_center/internal/mqtt_ingest", type="http", auth="none", methods=["POST"], csrf=False)
    def mqtt_ingest(self, **kwargs):
        def apply(data):
            if not isinstance(data.get("topic"), str) or not isinstance(data.get("payload"), str):
                raise ValueError("topic and payload are required")
            request.env["iot.mqtt.message"].sudo()._create_from_mqtt(data["topic"], data["payload"], retained=bool(data.get("retained")), received_at=envelope(data)[1])
            return {"ok": True, "event_id": data["event_id"]}
        return self._dispatch("mqtt", apply)

    @http.route("/iot_control_center/internal/th_ingest_json", type="http", auth="none", methods=["POST"], csrf=False)
    def th_ingest_json(self, **kwargs):
        return self._dispatch("th.json", lambda data: process_ingest_payload(request.env, data), receipt=False)

    @http.route("/iot_control_center/internal/th_ingest_binary", type="http", auth="none", methods=["POST"], csrf=False)
    def th_ingest_binary(self, **kwargs):
        return self._dispatch("th.binary", lambda data: process_ingest_payload(request.env, data, binary=True), receipt=False)

    @http.route("/iot_control_center/internal/openwrt_inventory", type="http", auth="none", methods=["POST"], csrf=False)
    def openwrt_inventory(self, **kwargs):
        return self._dispatch("openwrt.inventory", lambda data: {"ok": True, **request.env["iot.openwrt.ap"].sudo()._get_heartbeat_inventory()}, receipt=False)

    @http.route("/iot_control_center/internal/openwrt_heartbeat", type="http", auth="none", methods=["POST"], csrf=False)
    def openwrt_heartbeat(self, **kwargs):
        def apply(data):
            if not request.env["iot.openwrt.ap"].sudo()._apply_heartbeat_result(data):
                raise ValueError("unknown AP")
            return {"ok": True, "event_id": data["event_id"]}
        return self._dispatch("openwrt.heartbeat", apply)
