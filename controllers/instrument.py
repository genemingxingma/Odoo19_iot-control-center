import base64
import hashlib
import json
import secrets

from odoo import http
from odoo.http import request
from werkzeug.exceptions import RequestEntityTooLarge
from ..core.instruments import MAX_BODY, identifier


class InstrumentController(http.Controller):
    def _device(self, uid):
        identifier(uid)
        # Explicit enrollment only; incoming identity never creates/rebinds a device.
        rec = request.env["iot.instrument"].sudo().search([("uid", "=", uid), ("active", "=", True)], limit=1)
        token = request.httprequest.headers.get("X-Instrument-Token", "")
        if not rec or not rec.token_hash or not 32 <= len(token) <= 128:
            return None
        return rec if secrets.compare_digest(rec.token_hash, hashlib.sha256(token.encode()).hexdigest()) else None

    @http.route("/iot_control_center/instrument/<string:uid>/programs", type="http", auth="none", methods=["GET"], csrf=False)
    def programs(self, uid, **kwargs):
        try:
            rec = self._device(uid)
            if not rec or rec.kind != "washer":
                return request.make_response("Unauthorized", status=401)
            body, checksum = rec._program_catalog()
            etag = '"' + checksum + '"'
            headers = [("Cache-Control", "no-store"), ("ETag", etag),
                       ("X-Catalog-SHA256", checksum), ("Content-Type", "application/json")]
            if request.httprequest.headers.get("If-None-Match") == etag:
                return request.make_response("", status=304, headers=headers)
            return request.make_response(body, headers=headers)
        except (ValueError, TypeError, KeyError):
            return request.make_json_response({"ok": False, "error": "catalog unavailable"}, status=503)

    @http.route("/iot_control_center/instrument/<string:uid>/exchange", type="http", auth="none", methods=["POST"], csrf=False, readonly=False)
    def exchange(self, uid, **kwargs):
        try:
            rec = self._device(uid)
            if not rec:
                return request.make_json_response({"ok": False}, status=401)
            request.httprequest.max_content_length = MAX_BODY
            raw = request.httprequest.get_data(cache=False)
            if len(raw) > MAX_BODY:
                raise ValueError("body too large")
            data = json.loads(raw)
            with request.env.cr.savepoint():
                result = rec._exchange(data)
            return request.make_json_response(result)
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RequestEntityTooLarge):
            return request.make_json_response({"ok": False, "error": "invalid instrument event"}, status=400)

    @http.route("/iot_control_center/instrument/<string:uid>/release/<string:release>/<string:part>", type="http", auth="none", methods=["GET"], csrf=False)
    def firmware(self, uid, release, part, **kwargs):
        try:
            rec = self._device(uid)
            identifier(release)
        except ValueError:
            rec = None
        if not rec:
            return request.make_response("Unauthorized", status=401)
        package = request.env["iot.instrument.release"].sudo().search([("uid", "=", release),
            ("company_id", "=", rec.company_id.id), ("kind", "=", rec.kind), ("hardware", "=", rec.hardware)], limit=1)
        if not package or part not in {"manifest", "binary"}:
            return request.make_response("Not found", status=404)
        headers = [("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")]
        if part == "manifest":
            return request.make_response(package.manifest, headers=headers + [("Content-Type", "application/json")])
        return request.make_response(base64.b64decode(package.binary), headers=headers + [("Content-Type", "application/octet-stream")])
