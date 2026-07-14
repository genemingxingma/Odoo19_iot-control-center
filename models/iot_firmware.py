import base64
import binascii
import hashlib
from urllib.parse import urlencode

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
    image_flash_mode = fields.Selection(
        [("qio", "QIO"), ("qout", "QOUT"), ("dio", "DIO"), ("dout", "DOUT"), ("unknown", "Unknown")],
        compute="_compute_image_metadata",
        store=True,
    )
    image_flash_size = fields.Char(compute="_compute_image_metadata", store=True)
    image_compatible = fields.Boolean(compute="_compute_image_metadata", store=True)
    quarantined = fields.Boolean(default=False, help="Quarantined firmware cannot be pushed to devices.")
    quarantine_reason = fields.Char()
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

    @api.depends("file")
    def _compute_image_metadata(self):
        flash_modes = {0: "qio", 1: "qout", 2: "dio", 3: "dout"}
        flash_sizes = {0: "512KB", 1: "256KB", 2: "1MB", 3: "2MB", 4: "4MB", 8: "8MB", 9: "16MB"}
        for rec in self:
            mode = "unknown"
            size = "Unknown"
            compatible = False
            try:
                payload = rec.file.encode() if isinstance(rec.file, str) else rec.file
                raw = base64.b64decode(payload, validate=True)
                if len(raw) >= 4 and raw[0] == 0xE9:
                    mode = flash_modes.get(raw[2], "unknown")
                    size = flash_sizes.get((raw[3] >> 4) & 0x0F, "Unknown")
                    compatible = mode == "dout" and size == "1MB"
            except (binascii.Error, ValueError, TypeError):
                pass
            rec.image_flash_mode = mode
            rec.image_flash_size = size
            rec.image_compatible = compatible

    @api.constrains("filename", "file")
    def _check_filename_bin(self):
        for rec in self:
            if rec.file and rec.filename and not rec.filename.lower().endswith(".bin"):
                raise UserError(_("Firmware file must be a .bin file."))

    @api.constrains("file")
    def _check_relay_image_compatibility(self):
        for rec in self:
            if rec.file and not rec.image_compatible:
                raise UserError(
                    _(
                        "Relay firmware must be an ESP8266 1MB/DOUT image. "
                        "Detected flash mode: %(mode)s; flash size: %(size)s.",
                        mode=rec.image_flash_mode or "unknown",
                        size=rec.image_flash_size or "unknown",
                    )
                )

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
        if self.quarantined or not self.image_compatible:
            raise UserError(self.quarantine_reason or _("This firmware is quarantined or incompatible with relay hardware."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Push Firmware"),
            "res_model": "iot.firmware.push.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_firmware_id": self.id, "default_company_id": self.company_id.id},
        }

    def build_download_url(self, device, base_url=None):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        base_url = base_url or icp.get_param("iot_control_center.firmware_base_url") or icp.get_param("web.base.url")
        if not base_url:
            raise UserError(_("web.base.url is not configured."))
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")
        query = urlencode({"s": device.serial, "t": device.auth_token, "db": self.env.cr.dbname})
        return f"{base_url}/f/{self.id}?{query}"

    def build_download_urls(self, device):
        self.ensure_one()
        public_url = self.build_download_url(device)
        internal_base = device.company_id.get_iot_internal_ota_base_url() if device.company_id else False
        internal_url = self.build_download_url(device, base_url=internal_base) if internal_base else False
        if internal_url and internal_url != public_url:
            return internal_url, public_url
        return public_url, False
