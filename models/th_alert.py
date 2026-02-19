from odoo import fields, models


class IoTTHAlert(models.Model):
    _name = "iot.th.alert"
    _description = "Temperature/Humidity Alert"
    _order = "occurred_at desc, id desc"

    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="cascade")
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="sensor_id.company_id", store=True, index=True)

    alert_type = fields.Selection(
        [
            ("temp_high", "Temperature High"),
            ("temp_low", "Temperature Low"),
            ("hum_high", "Humidity High"),
            ("hum_low", "Humidity Low"),
        ],
        required=True,
        index=True,
    )
    threshold_value = fields.Float(required=True)
    actual_value = fields.Float(required=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now)

    state = fields.Selection([("open", "Open"), ("closed", "Closed")], default="open", index=True)
    closed_at = fields.Datetime()
    note = fields.Text()
