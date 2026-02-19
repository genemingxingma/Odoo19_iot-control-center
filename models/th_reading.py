from odoo import fields, models


class IoTTHReading(models.Model):
    _name = "iot.th.reading"
    _description = "Temperature/Humidity Reading"
    _order = "reported_at desc, id desc"

    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="cascade")
    sensor_code = fields.Char(related="sensor_id.probe_code", string="Sensor ID", store=True, index=True)
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="cascade")
    node_id = fields.Char(related="sensor_id.node_id", string="Node ID", store=True, index=True)
    company_id = fields.Many2one(related="sensor_id.company_id", store=True, index=True)

    reported_at = fields.Datetime(required=True, index=True)
    temperature = fields.Float(required=True)
    humidity = fields.Float(required=True)
    raw_payload = fields.Text()
