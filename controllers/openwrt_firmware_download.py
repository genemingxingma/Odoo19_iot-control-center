import base64
import secrets

from odoo import http
from odoo.http import request


class IoTOpenWrtFirmwareController(http.Controller):
    def _authorized(self):
        expected = (request.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_token") or "").strip()
        provided = (request.httprequest.headers.get("X-IoT-Middleware-Token") or "").strip()
        return bool(expected) and secrets.compare_digest(provided, expected)

    @http.route(
        "/iot_control_center/openwrt/firmware/<int:firmware_id>/download",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def download_openwrt_firmware(self, firmware_id, **kwargs):
        if not self._authorized():
            return request.not_found()
        firmware = request.env["iot.openwrt.firmware"].sudo().browse(firmware_id)
        if not firmware.exists() or not firmware.file:
            return request.not_found()
        ap_id = kwargs.get("ap_id")
        token = (kwargs.get("token") or "").strip()
        if not ap_id or not token:
            return request.not_found()
        try:
            ap_id = int(ap_id)
        except (TypeError, ValueError):
            return request.not_found()
        ap = request.env["iot.openwrt.ap"].sudo().search(
            [("id", "=", ap_id), ("auth_token", "=", token)],
            limit=1,
        )
        if not ap:
            return request.not_found()
        if firmware.company_id and firmware.company_id != ap.company_id:
            return request.not_found()
        content = base64.b64decode(firmware.file)
        headers = [
            ("Content-Type", "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", f'attachment; filename="{firmware.filename or "openwrt.bin"}"'),
        ]
        return request.make_response(content, headers=headers)
