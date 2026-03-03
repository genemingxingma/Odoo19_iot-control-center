import base64
import json
import logging

from odoo import http
from odoo.http import request

from ..services.tcp_service import process_ingest_payload

_logger = logging.getLogger(__name__)


class IoTInternalIngestController(http.Controller):
    def _check_token(self):
        expected = (request.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_token") or "").strip()
        provided = (request.httprequest.headers.get("X-IoT-Middleware-Token") or "").strip()
        # Keep backward compatibility: if token is empty in config, allow requests.
        return (not expected) or (provided == expected)

    def _parse_json(self):
        raw = request.httprequest.data or b"{}"
        return json.loads(raw.decode("utf-8"))

    @http.route("/iot_control_center/internal/mqtt_ingest", type="http", auth="none", methods=["POST"], csrf=False)
    def mqtt_ingest(self, **kwargs):
        try:
            if not self._check_token():
                return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
            data = self._parse_json()
            topic = data.get("topic")
            payload = data.get("payload")
            if not topic or payload is None:
                return request.make_json_response({"ok": False, "error": "missing topic/payload"}, status=400)
            request.env["iot.mqtt.message"].sudo().create_from_mqtt(topic, str(payload))
            return request.make_json_response({"ok": True})
        except Exception as exc:
            _logger.exception("Internal MQTT ingest failed: %s", exc)
            return request.make_json_response({"ok": False, "error": str(exc)}, status=500)

    @http.route("/iot_control_center/internal/th_ingest_json", type="http", auth="none", methods=["POST"], csrf=False)
    def th_ingest_json(self, **kwargs):
        try:
            if not self._check_token():
                return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
            data = self._parse_json()
            payload_text = data.get("payload_text")
            source_ip = data.get("source_ip")
            source_port = data.get("source_port")
            if not payload_text:
                return request.make_json_response({"ok": False, "error": "missing payload_text"}, status=400)
            process_ingest_payload(
                request.env,
                payload_text=str(payload_text),
                source_ip=source_ip,
                source_port=source_port,
            )
            return request.make_json_response({"ok": True})
        except Exception as exc:
            _logger.exception("Internal TH JSON ingest failed: %s", exc)
            return request.make_json_response({"ok": False, "error": str(exc)}, status=500)

    @http.route("/iot_control_center/internal/th_ingest_binary", type="http", auth="none", methods=["POST"], csrf=False)
    def th_ingest_binary(self, **kwargs):
        try:
            if not self._check_token():
                return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
            data = self._parse_json()
            frame_b64 = data.get("frame_b64")
            source_ip = data.get("source_ip")
            source_port = data.get("source_port")
            if not frame_b64:
                return request.make_json_response({"ok": False, "error": "missing frame_b64"}, status=400)
            frame = base64.b64decode(frame_b64)
            process_ingest_payload(
                request.env,
                frame_bytes=frame,
                source_ip=source_ip,
                source_port=source_port,
            )
            return request.make_json_response({"ok": True})
        except Exception as exc:
            _logger.exception("Internal TH binary ingest failed: %s", exc)
            return request.make_json_response({"ok": False, "error": str(exc)}, status=500)
