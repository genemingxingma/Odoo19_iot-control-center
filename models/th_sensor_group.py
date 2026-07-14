from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class IoTTHSensorGroup(models.Model):
    _name = "iot.th.sensor.group"
    _description = "Temperature/Humidity Sensor Group"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    note = fields.Text()

    temperature_low = fields.Float(default=5.0, required=True)
    temperature_high = fields.Float(default=35.0, required=True)
    humidity_low = fields.Float(default=30.0, required=True)
    humidity_high = fields.Float(default=75.0, required=True)

    sensor_ids = fields.One2many("iot.th.sensor", "group_id", string="Sensors")
    sensor_count = fields.Integer(compute="_compute_sensor_count")

    def _compute_sensor_count(self):
        for rec in self:
            rec.sensor_count = len(rec.sensor_ids)

    @api.constrains("temperature_low", "temperature_high", "humidity_low", "humidity_high")
    def _check_thresholds(self):
        for rec in self:
            if rec.temperature_low > rec.temperature_high:
                raise ValidationError(_("Temperature low limit must not exceed high limit."))
            if rec.humidity_low > rec.humidity_high:
                raise ValidationError(_("Humidity low limit must not exceed high limit."))

    def action_open_sensors(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sensors",
            "res_model": "iot.th.sensor",
            "view_mode": "list,form",
            "domain": [("group_id", "=", self.id)],
        }
