from odoo import fields, models


class IoTOpenwrtTemplateSSID(models.Model):
    _name = "iot.openwrt.template.ssid"
    _description = "OpenWrt Template SSID"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one("iot.openwrt.template", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    band = fields.Selection(
        [
            ("2g", "2.4G"),
            ("5g", "5G"),
        ],
        required=True,
        default="2g",
    )
    enabled = fields.Boolean(default=True)
    ssid = fields.Char(required=True)
    encryption = fields.Selection(
        [
            ("none", "Open"),
            ("psk2", "WPA2-PSK"),
            ("sae-mixed", "WPA2/WPA3 Mixed"),
            ("sae", "WPA3-SAE"),
        ],
        default="psk2",
        required=True,
    )
    key = fields.Char()
    hidden = fields.Boolean()
