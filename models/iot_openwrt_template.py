import json

from odoo import fields, models


class IoTOpenwrtTemplate(models.Model):
    _name = "iot.openwrt.template"
    _description = "OpenWrt Configuration Template"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    notes = fields.Text(translate=True)

    country_code = fields.Char(default="TH")
    system_hostname = fields.Char()
    timezone_name = fields.Char(default="Asia/Bangkok")

    ssid_entry_ids = fields.One2many("iot.openwrt.template.ssid", "template_id", string="SSID Entries")
    wifi24_ssid_count = fields.Integer(compute="_compute_ssid_counts")
    wifi5_ssid_count = fields.Integer(compute="_compute_ssid_counts")

    wifi24_enabled = fields.Boolean(string="2.4G Enabled", default=True)
    wifi24_ssid = fields.Char(string="2.4G SSID")
    wifi24_encryption = fields.Selection(
        [
            ("none", "Open"),
            ("psk2", "WPA2-PSK"),
            ("sae-mixed", "WPA2/WPA3 Mixed"),
            ("sae", "WPA3-SAE"),
        ],
        string="2.4G Encryption",
        default="psk2",
    )
    wifi24_key = fields.Char(string="2.4G Password")
    wifi24_hidden = fields.Boolean(string="2.4G Hidden SSID")
    wifi24_channel = fields.Char(string="2.4G Channel", default="auto")

    wifi5_enabled = fields.Boolean(string="5G Enabled", default=True)
    wifi5_ssid = fields.Char(string="5G SSID")
    wifi5_encryption = fields.Selection(
        [
            ("none", "Open"),
            ("psk2", "WPA2-PSK"),
            ("sae-mixed", "WPA2/WPA3 Mixed"),
            ("sae", "WPA3-SAE"),
        ],
        string="5G Encryption",
        default="psk2",
    )
    wifi5_key = fields.Char(string="5G Password")
    wifi5_hidden = fields.Boolean(string="5G Hidden SSID")
    wifi5_channel = fields.Char(string="5G Channel", default="auto")

    def _compute_ssid_counts(self):
        for rec in self:
            rec.wifi24_ssid_count = len(rec.ssid_entry_ids.filtered(lambda line: line.band == "2g"))
            rec.wifi5_ssid_count = len(rec.ssid_entry_ids.filtered(lambda line: line.band == "5g"))

    def _build_ssid_entries(self, band):
        self.ensure_one()
        entries = []
        if band == "2g":
            child_lines = self.ssid_entry_ids.filtered(lambda line: line.band == "2g")
            if child_lines:
                for line in child_lines.sorted(key=lambda r: (r.sequence, r.id)):
                    entries.append(
                        {
                            "enabled": bool(line.enabled),
                            "ssid": (line.ssid or "").strip() or None,
                            "encryption": line.encryption or None,
                            "key": line.key or None,
                            "hidden": bool(line.hidden),
                        }
                    )
            elif (self.wifi24_ssid or "").strip():
                entries.append(
                    {
                        "enabled": bool(self.wifi24_enabled),
                        "ssid": (self.wifi24_ssid or "").strip() or None,
                        "encryption": self.wifi24_encryption or None,
                        "key": self.wifi24_key or None,
                        "hidden": bool(self.wifi24_hidden),
                    }
                )
        else:
            child_lines = self.ssid_entry_ids.filtered(lambda line: line.band == "5g")
            if child_lines:
                for line in child_lines.sorted(key=lambda r: (r.sequence, r.id)):
                    entries.append(
                        {
                            "enabled": bool(line.enabled),
                            "ssid": (line.ssid or "").strip() or None,
                            "encryption": line.encryption or None,
                            "key": line.key or None,
                            "hidden": bool(line.hidden),
                        }
                    )
            elif (self.wifi5_ssid or "").strip():
                entries.append(
                    {
                        "enabled": bool(self.wifi5_enabled),
                        "ssid": (self.wifi5_ssid or "").strip() or None,
                        "encryption": self.wifi5_encryption or None,
                        "key": self.wifi5_key or None,
                        "hidden": bool(self.wifi5_hidden),
                    }
                )
        return entries

    def to_middleware_payload(self):
        self.ensure_one()
        return {
            "country_code": (self.country_code or "").strip() or None,
            "system_hostname": (self.system_hostname or "").strip() or None,
            "timezone_name": (self.timezone_name or "").strip() or None,
            "wifi24": {
                "enabled": bool(self.wifi24_enabled),
                "channel": (self.wifi24_channel or "").strip() or None,
                "entries": self._build_ssid_entries("2g"),
            },
            "wifi5": {
                "enabled": bool(self.wifi5_enabled),
                "channel": (self.wifi5_channel or "").strip() or None,
                "entries": self._build_ssid_entries("5g"),
            },
        }

    def payload_preview(self):
        self.ensure_one()
        return json.dumps(self.to_middleware_payload(), ensure_ascii=False, indent=2)
