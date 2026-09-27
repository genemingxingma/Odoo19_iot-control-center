import base64
import hashlib
import json
import secrets

from odoo import http
from odoo.http import request
from werkzeug.exceptions import RequestEntityTooLarge
from ..core.instruments import MAX_BODY, discovery, identifier

MAX_DISCOVERY_BODY = 2048


class InstrumentController(http.Controller):
    def _device(self, uid):
        identifier(uid)
        # Explicit enrollment only; incoming identity never creates/rebinds a device.
        rec = request.env["iot.instrument"].sudo().search([("uid", "=", uid), ("active", "=", True)], limit=1)
        token = request.httprequest.headers.get("X-Instrument-Token", "")
        if not rec or not rec.token_hash or not 32 <= len(token) <= 128:
            return None
        return rec if secrets.compare_digest(rec.token_hash, hashlib.sha256(token.encode()).hexdigest()) else None

    @http.route("/iot_control_center/instrument/discover", type="http", auth="none", methods=["POST"], csrf=False, readonly=False)
    def discover(self, **kwargs):
        """Claim an operator-preauthorized Device ID without accepting company data from firmware."""
        try:
            request.httprequest.max_content_length = MAX_DISCOVERY_BODY
            raw = request.httprequest.get_data(cache=False)
            if len(raw) > MAX_DISCOVERY_BODY:
                raise ValueError("body too large")
            values = discovery(json.loads(raw))
            token = request.httprequest.headers.get("X-Instrument-Token", "")
            if not 32 <= len(token) <= 128 or not secrets.compare_digest(token.strip(), token):
                return request.make_json_response({"ok": False, "bound": False}, status=401)
            instrument = request.env["iot.instrument"].sudo().search([
                ("device_id", "=", values["device_id"]), ("active", "=", True)], limit=1)
            # Unknown IDs are not persisted. An IoT manager must first authorize
            # the exact ID and choose its company in the binding wizard.
            if not instrument:
                return request.make_json_response({"ok": True, "bound": False})
            request.env.cr.execute("SELECT id FROM iot_instrument WHERE id=%s FOR UPDATE", [instrument.id])
            instrument.invalidate_recordset()
            if instrument.kind != values["kind"]:
                raise ValueError("instrument type mismatch")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            if instrument.token_hash and not secrets.compare_digest(instrument.token_hash, token_hash):
                return request.make_json_response({"ok": False, "bound": False}, status=409)
            updates = {"hardware": values["hardware"], "firmware": values["firmware"]}
            if not instrument.token_hash:
                updates["token_hash"] = token_hash
            instrument.write(updates)
            return request.make_json_response({"ok": True, "bound": True, "device_id": values["device_id"]})
        except (ValueError, TypeError, KeyError, OverflowError, RequestEntityTooLarge):
            return request.make_json_response({"ok": False, "bound": False, "error": "invalid discovery request"}, status=400)

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
