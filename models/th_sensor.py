from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class IoTTHSensor(models.Model):
    _name = "iot.th.sensor"
    _description = "Temperature/Humidity Sensor"

    name = fields.Char(required=True)
    probe_code = fields.Char(string="Sensor ID", required=True, index=True)
    active = fields.Boolean(default=True)

    gateway_id = fields.Many2one("iot.th.gateway", required=True, ondelete="cascade")
    node_id = fields.Char(string="Node ID", required=True, index=True)
    company_id = fields.Many2one("res.company", index=True)
    location_id = fields.Many2one("iot.location", string="Location", domain="[('company_id', '=', company_id)]")
    location_detail = fields.Char(string="Location Detail")

    temperature_low = fields.Float(default=5.0)
    temperature_high = fields.Float(default=35.0)
    humidity_low = fields.Float(default=30.0)
    humidity_high = fields.Float(default=75.0)

    last_temperature = fields.Float()
    last_humidity = fields.Float()
    last_battery_voltage = fields.Float(string="Battery Voltage (V)")
    last_reported_at = fields.Datetime()
    reading_count = fields.Integer(default=0)

    stats_window_hours = fields.Integer(default=24)
    avg_temperature = fields.Float(compute="_compute_stats")
    avg_humidity = fields.Float(compute="_compute_stats")
    min_temperature = fields.Float(compute="_compute_stats")
    max_temperature = fields.Float(compute="_compute_stats")
    min_humidity = fields.Float(compute="_compute_stats")
    max_humidity = fields.Float(compute="_compute_stats")

    reading_ids = fields.One2many("iot.th.reading", "sensor_id")

    _sql_constraints = [
        (
            "iot_th_sensor_node_probe_uniq",
            "unique(node_id, probe_code)",
            "Sensor ID must be unique by node + probe.",
        ),
    ]

    @api.model
    def find_bind_candidates(self, node_id, probe_code=None, require_online=False):
        nid = (node_id or "").strip()
        if not nid:
            raise UserError("Node ID is required")
        domain = [("node_id", "=ilike", nid)]
        probe = (probe_code or "").strip()
        if probe:
            domain.append(("probe_code", "=ilike", probe))
        sensors = self.sudo().search(domain, order="last_reported_at desc, id desc")
        if not sensors:
            raise UserError("No sensor found for this Node ID.")
        if require_online:
            timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.iot_th_online_timeout_sec", 900))
            now = fields.Datetime.now()
            offline = sensors.filtered(lambda s: not s.last_reported_at or (now - s.last_reported_at) > timedelta(seconds=timeout))
            if offline:
                if len(sensors) == 1:
                    raise UserError("Node is offline. Please wait for fresh data before binding.")
                sensors = sensors - offline
                if not sensors:
                    raise UserError("All matched sensors are offline. Please wait for fresh data before binding.")
        return sensors.with_env(self.env)

    @api.model
    def bind_by_node(self, node_id, probe_code=None, company=None, location=None, location_detail=None):
        sensors = self.find_bind_candidates(node_id, probe_code=probe_code, require_online=True)
        target_company = company or self.env.company
        conflict = sensors.filtered(lambda s: s.company_id and s.company_id != target_company)
        if conflict:
            raise UserError("This node is already bound to another company.")
        vals = {"company_id": target_company.id}
        if location:
            vals["location_id"] = location.id
        if location_detail is not None:
            vals["location_detail"] = location_detail
        sensors.write(vals)
        return sensors.with_env(self.env)

    def action_unbind(self):
        self.write({"company_id": False, "location_id": False, "location_detail": False})

    @api.depends("last_reported_at", "stats_window_hours")
    def _compute_stats(self):
        reading_model = self.env["iot.th.reading"]
        for rec in self:
            now = fields.Datetime.now()
            since = now - timedelta(hours=max(rec.stats_window_hours or 24, 1))
            rows = reading_model.search_read(
                [("sensor_id", "=", rec.id), ("reported_at", ">=", since)],
                ["temperature", "humidity"],
                limit=5000,
            )
            if not rows:
                rec.avg_temperature = 0.0
                rec.avg_humidity = 0.0
                rec.min_temperature = 0.0
                rec.max_temperature = 0.0
                rec.min_humidity = 0.0
                rec.max_humidity = 0.0
                continue

            temps = [r["temperature"] for r in rows if r.get("temperature") is not None]
            hums = [r["humidity"] for r in rows if r.get("humidity") is not None]

            rec.avg_temperature = sum(temps) / len(temps) if temps else 0.0
            rec.min_temperature = min(temps) if temps else 0.0
            rec.max_temperature = max(temps) if temps else 0.0

            rec.avg_humidity = sum(hums) / len(hums) if hums else 0.0
            rec.min_humidity = min(hums) if hums else 0.0
            rec.max_humidity = max(hums) if hums else 0.0

    def apply_reading(self, temperature, humidity, reported_at, battery_voltage=None):
        alert_model = self.env["iot.th.alert"]
        for rec in self:
            rec.last_temperature = temperature
            rec.last_humidity = humidity
            if battery_voltage is not None:
                rec.last_battery_voltage = battery_voltage
            rec.last_reported_at = reported_at
            rec.reading_count += 1

            checks = []
            if temperature > rec.temperature_high:
                checks.append(("temp_high", rec.temperature_high, temperature))
            elif temperature < rec.temperature_low:
                checks.append(("temp_low", rec.temperature_low, temperature))

            if humidity > rec.humidity_high:
                checks.append(("hum_high", rec.humidity_high, humidity))
            elif humidity < rec.humidity_low:
                checks.append(("hum_low", rec.humidity_low, humidity))

            for alert_type, threshold, actual in checks:
                already_open = alert_model.search_count(
                    [
                        ("sensor_id", "=", rec.id),
                        ("alert_type", "=", alert_type),
                        ("state", "=", "open"),
                    ]
                )
                if not already_open:
                    alert_model.create(
                        {
                            "sensor_id": rec.id,
                            "gateway_id": rec.gateway_id.id,
                            "alert_type": alert_type,
                            "threshold_value": threshold,
                            "actual_value": actual,
                            "occurred_at": reported_at,
                        }
                    )

            # Close opposite alerts once value returns to normal range.
            if rec.temperature_low <= temperature <= rec.temperature_high:
                alert_model.search(
                    [
                        ("sensor_id", "=", rec.id),
                        ("alert_type", "in", ["temp_high", "temp_low"]),
                        ("state", "=", "open"),
                    ]
                ).write({"state": "closed", "closed_at": fields.Datetime.now()})

            if rec.humidity_low <= humidity <= rec.humidity_high:
                alert_model.search(
                    [
                        ("sensor_id", "=", rec.id),
                        ("alert_type", "in", ["hum_high", "hum_low"]),
                        ("state", "=", "open"),
                    ]
                ).write({"state": "closed", "closed_at": fields.Datetime.now()})
