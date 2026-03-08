import base64

from odoo import http
from odoo.http import request


class IoTOpenWrtFirmwareController(http.Controller):
    def _authorized(self):
        expected = (request.env["ir.config_parameter"].sudo().get_param("iot_control_center.middleware_token") or "").strip()
        provided = (request.httprequest.headers.get("X-IoT-Middleware-Token") or "").strip()
        return (not expected) or (provided == expected)

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
        content = base64.b64decode(firmware.file)
        headers = [
            ("Content-Type", "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", f'attachment; filename="{firmware.filename or "openwrt.bin"}"'),
        ]
        return request.make_response(content, headers=headers)
