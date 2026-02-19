import base64

from odoo import http
from odoo.http import request


class IoTFirmwareController(http.Controller):
    def _download_impl(self, firmware_id, serial=None, token=None):
        if not serial or not token:
            return request.not_found()

        device = request.env["iot.device"].sudo().search([("serial", "=ilike", serial), ("auth_token", "=", token)], limit=1)
        if not device:
            return request.not_found()

        firmware = request.env["iot.firmware"].sudo().browse(firmware_id)
        if not firmware.exists() or not firmware.file:
            return request.not_found()

        content = base64.b64decode(firmware.file)
        headers = [
            ("Content-Type", "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", f'attachment; filename="{firmware.filename or "firmware.bin"}"'),
        ]
        return request.make_response(content, headers=headers)

    @http.route("/iot_control_center/firmware/<int:firmware_id>/download", type="http", auth="public", methods=["GET"], csrf=False)
    def download_firmware(self, firmware_id, serial=None, token=None, **kwargs):
        return self._download_impl(firmware_id, serial=serial, token=token)

    @http.route("/f/<int:firmware_id>", type="http", auth="public", methods=["GET"], csrf=False)
    def download_firmware_short(self, firmware_id, s=None, t=None, **kwargs):
        return self._download_impl(firmware_id, serial=s, token=t)
