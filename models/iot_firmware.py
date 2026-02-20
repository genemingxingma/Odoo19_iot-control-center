import base64
import binascii
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IoTFirmware(models.Model):
    _name = "iot.firmware"
    _description = "IoT Firmware"
    _order = "id desc"

    name = fields.Char(required=True)
    version = fields.Char(required=True)
    file = fields.Binary(required=True, attachment=True)
    filename = fields.Char(required=True, default="firmware.bin")
    checksum = fields.Char(compute="_compute_checksum", store=True)
    note = fields.Text()
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.depends("file")
    def _compute_checksum(self):
        for rec in self:
            if not rec.file:
                rec.checksum = False
                continue
            try:
                payload = rec.file.encode() if isinstance(rec.file, str) else rec.file
                raw = base64.b64decode(payload, validate=True)
                rec.checksum = hashlib.sha256(raw).hexdigest()
            except (binascii.Error, ValueError, TypeError):
                # In web_save/bin_size contexts, binary fields may be represented
                # by size strings instead of raw base64 payload.
                rec.checksum = rec._origin.checksum if rec._origin and rec._origin.id else False

    @api.constrains("filename", "file")
    def _check_filename_bin(self):
        for rec in self:
            if rec.file and rec.filename and not rec.filename.lower().endswith(".bin"):
                raise UserError(_("Firmware file must be a .bin file."))

    @api.model
    def _fallback_filename(self, vals):
        filename = (vals.get("filename") or "").strip()
        if filename:
            return filename if filename.lower().endswith(".bin") else f"{filename}.bin"
        base = (vals.get("name") or vals.get("version") or "firmware").strip() or "firmware"
        return f"{base}.bin"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("file"):
                vals["filename"] = self._fallback_filename(vals)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("file"):
            vals = dict(vals)
            vals["filename"] = self._fallback_filename(vals)
        return super().write(vals)

    def action_open_push_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Push Firmware"),
            "res_model": "iot.firmware.push.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_firmware_id": self.id, "default_company_id": self.company_id.id},
        }

    def build_download_url(self, device):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        base_url = icp.get_param("iot_control_center.firmware_base_url") or icp.get_param("web.base.url")
        if not base_url:
            raise UserError(_("web.base.url is not configured."))
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            base_url = f"http://{base_url}"
        base_url = base_url.rstrip("/")
        return f"{base_url}/f/{self.id}?s={device.serial}&t={device.auth_token}"
