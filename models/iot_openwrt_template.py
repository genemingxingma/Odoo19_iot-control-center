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

    def to_middleware_payload(self):
        self.ensure_one()
        return {
            "country_code": (self.country_code or "").strip() or None,
            "system_hostname": (self.system_hostname or "").strip() or None,
            "timezone_name": (self.timezone_name or "").strip() or None,
            "wifi24": {
                "enabled": bool(self.wifi24_enabled),
                "ssid": (self.wifi24_ssid or "").strip() or None,
                "encryption": self.wifi24_encryption or None,
                "key": self.wifi24_key or None,
                "hidden": bool(self.wifi24_hidden),
                "channel": (self.wifi24_channel or "").strip() or None,
            },
            "wifi5": {
                "enabled": bool(self.wifi5_enabled),
                "ssid": (self.wifi5_ssid or "").strip() or None,
                "encryption": self.wifi5_encryption or None,
                "key": self.wifi5_key or None,
                "hidden": bool(self.wifi5_hidden),
                "channel": (self.wifi5_channel or "").strip() or None,
            },
        }

    def payload_preview(self):
        self.ensure_one()
        return json.dumps(self.to_middleware_payload(), ensure_ascii=False, indent=2)
