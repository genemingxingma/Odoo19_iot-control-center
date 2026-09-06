"""Immutable raw observations. Aggregation is a query, never a replacement row."""
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from ..core.telemetry import measurement

class IoTTHReading(models.Model):
    _name = "iot.th.reading"
    _description = "Temperature/Humidity Reading"
    _order = "reported_at desc, id desc"

    event_id = fields.Char(required=True, index=True, readonly=True)
    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="restrict")
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    sensor_code = fields.Char(string="Sensor Channel", readonly=True)
    node_id = fields.Char(string="Node ID", readonly=True)
    sensor_location_id = fields.Many2one("stock.location", string="Sensor Location", readonly=True)
    sensor_location_detail = fields.Char(string="Location Detail", readonly=True)
    sensor_group_id = fields.Many2one("iot.th.sensor.group", string="Sensor Group", readonly=True)
    reported_at = fields.Datetime(required=True, index=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    temperature = fields.Float(string="Temperature (C)", required=True, digits=(16, 2), aggregator="avg")
    humidity = fields.Float(string="Relative Humidity (%RH)", required=True, digits=(16, 2), aggregator="avg")
    temperature_min = fields.Float(related="temperature", store=True, aggregator="min")
    temperature_max = fields.Float(related="temperature", store=True, aggregator="max")
    humidity_min = fields.Float(related="humidity", store=True, aggregator="min")
    humidity_max = fields.Float(related="humidity", store=True, aggregator="max")
    sample_count = fields.Integer(default=1, readonly=True, aggregator="sum")
    _event_sensor_uniq = models.Constraint("UNIQUE(sensor_id, event_id)", "A probe event can only be stored once.")
    _raw_only = models.Constraint("CHECK(sample_count = 1)", "Only raw samples are accepted.")

    def init(self):
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS iot_th_raw_company_time_idx ON iot_th_reading(company_id, reported_at DESC, sensor_id)")
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS iot_th_raw_sensor_time_idx ON iot_th_reading(sensor_id, reported_at DESC)")

    @api.model_create_multi
    def create(self, vals_list):
        result = []
        for source in vals_list:
            values = dict(source)
            if values.get("sample_count", 1) != 1 or values.get("is_hourly_rollup") or values.get("is_daily_rollup"):
                raise ValidationError(_("Only raw samples are accepted."))
            sensor = self.env["iot.th.sensor"].browse(values["sensor_id"])
            sensor.check_access("read")
            if not sensor.company_id or sensor.gateway_id.id != values["gateway_id"]:
                raise ValidationError(_("The probe must belong to a registered company gateway."))
            try:
                measurement(sensor.node_id, sensor.probe_code, values.get("temperature"), values.get("humidity"))
            except (ValueError, TypeError) as exc:
                raise ValidationError(_("Invalid temperature or humidity sample.")) from exc
            values.update(company_id=sensor.company_id.id, node_id=sensor.node_id, sensor_code=sensor.probe_code,
                          sensor_location_id=sensor.location_id.id, sensor_location_detail=sensor.location_detail,
                          sensor_group_id=sensor.group_id.id, sample_count=1)
            values.setdefault("event_id", uuid.uuid4().hex)
            result.append(values)
        return super().create(result)

    def write(self, vals):
        raise AccessError(_("Raw observations are immutable."))

    @api.model
    def _cron_purge_expired_readings(self, batch_size=10000):
        # No implicit retention policy and no commits inside a cron transaction.
        for company in self.env["res.company"].sudo().search([("iot_history_retention_days", ">", 0)]):
            cutoff = fields.Datetime.now() - timedelta(days=company.iot_history_retention_days)
            expired = self.sudo().search([("company_id", "=", company.id), ("reported_at", "<", cutoff),
                                           ("sensor_id.keep_full_history", "=", False)], limit=min(max(batch_size, 1), 10000))
            expired.unlink()

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        return super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
