import base64
import hashlib

from odoo import api, fields, models


class IoTOpenwrtFirmware(models.Model):
    _name = "iot.openwrt.firmware"
    _description = "OpenWrt Firmware Package"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    model_pattern = fields.Char(
        required=True,
        help="Firmware applies to AP model names containing this text, case-insensitive.",
    )
    version = fields.Char(required=True)
    filename = fields.Char(required=True)
    file = fields.Binary(required=True, attachment=True)
    checksum_sha256 = fields.Char(compute="_compute_checksum_sha256", store=True)
    notes = fields.Text(translate=True)

    @api.depends("file")
    def _compute_checksum_sha256(self):
        for rec in self:
            digest = ""
            if rec.file:
                try:
                    digest = hashlib.sha256(base64.b64decode(rec.file)).hexdigest()
                except Exception:
                    digest = ""
            rec.checksum_sha256 = digest
