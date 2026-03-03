from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class IoTTHSensor(models.Model):
    _name = "iot.th.sensor"
    _description = "Node Sensor Channel (Temp+Humidity)"

    name = fields.Char(required=True)
    probe_code = fields.Char(string="Sensor Channel", required=True, index=True)
    active = fields.Boolean(default=True)

    gateway_id = fields.Many2one("iot.th.gateway", required=True, ondelete="cascade")
    node_id = fields.Char(string="Node ID", required=True, index=True)
    company_id = fields.Many2one("res.company", index=True)
    location_id = fields.Many2one(
        "stock.location",
        string="Location",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    location_detail = fields.Char(string="Location Detail", translate=True)
    group_id = fields.Many2one(
        "iot.th.sensor.group",
        string="Sensor Group",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    temperature_low = fields.Float(default=5.0)
    temperature_high = fields.Float(default=35.0)
    humidity_low = fields.Float(default=30.0)
    humidity_high = fields.Float(default=75.0)
    effective_temperature_low = fields.Float(compute="_compute_effective_thresholds")
    effective_temperature_high = fields.Float(compute="_compute_effective_thresholds")
    effective_humidity_low = fields.Float(compute="_compute_effective_thresholds")
    effective_humidity_high = fields.Float(compute="_compute_effective_thresholds")
    threshold_source = fields.Selection(
        [("sensor", "Sensor"), ("group", "Group")],
        compute="_compute_effective_thresholds",
    )

    last_temperature = fields.Float()
    last_humidity = fields.Float()
    last_battery_voltage = fields.Float(string="Battery Voltage (V)")
    last_reported_at = fields.Datetime()
    reading_count = fields.Integer(default=0)

    stats_window_hours = fields.Integer(default=24)
    keep_full_history = fields.Boolean(
        string="Keep Full History",
        default=False,
        help="If enabled, this node keeps all raw readings and skips 30-day rollup.",
    )
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
            "Sensor Channel must be unique by Node ID + Channel.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for vals in vals_list:
            v = dict(vals)
            if v.get("node_id"):
                v["node_id"] = str(v["node_id"]).strip().upper()
            if v.get("probe_code"):
                v["probe_code"] = str(v["probe_code"]).strip().upper()
            normalized.append(v)
        return super().create(normalized)

    def write(self, vals):
        v = dict(vals)
        if v.get("node_id"):
            v["node_id"] = str(v["node_id"]).strip().upper()
        if v.get("probe_code"):
            v["probe_code"] = str(v["probe_code"]).strip().upper()
        return super().write(v)

    @api.model
    def find_bind_candidates(self, node_id, probe_code=None, require_online=False):
        nid = (node_id or "").strip()
        if not nid:
            raise UserError("Node ID is required")
        domain = [("node_id", "=", nid)]
        probe = (probe_code or "").strip()
        if probe:
            domain.append(("probe_code", "=", probe))
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
                [
                    ("sensor_id", "=", rec.id),
                    ("reported_at", ">=", since),
                    "|",
                    ("temperature", "!=", 0.0),
                    ("humidity", "!=", 0.0),
                ],
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

    @api.constrains("company_id", "group_id")
    def _check_group_company(self):
        for rec in self:
            if rec.group_id and rec.company_id and rec.group_id.company_id and rec.group_id.company_id != rec.company_id:
                raise UserError("Sensor Group company must match the sensor company.")

    def apply_reading(self, temperature, humidity, reported_at, battery_voltage=None):
        alert_model = self.env["iot.th.alert"]
        for rec in self:
            rec.last_temperature = temperature
            rec.last_humidity = humidity
            if battery_voltage is not None:
                rec.last_battery_voltage = battery_voltage
            rec.last_reported_at = reported_at
            rec.reading_count += 1

            t_low, t_high, h_low, h_high = rec._get_effective_threshold_values()
            checks = []
            if temperature > t_high:
                checks.append(("temp_high", t_high, temperature))
            elif temperature < t_low:
                checks.append(("temp_low", t_low, temperature))

            if humidity > h_high:
                checks.append(("hum_high", h_high, humidity))
            elif humidity < h_low:
                checks.append(("hum_low", h_low, humidity))

            open_alerts = alert_model.search(
                [
                    ("sensor_id", "=", rec.id),
                    ("state", "=", "open"),
                ]
            )
            open_types = set(open_alerts.mapped("alert_type"))
            for alert_type, threshold, actual in checks:
                if alert_type not in open_types:
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
            close_types = set()
            if t_low <= temperature <= t_high:
                close_types.update(["temp_high", "temp_low"])

            if h_low <= humidity <= h_high:
                close_types.update(["hum_high", "hum_low"])

            if close_types:
                to_close = open_alerts.filtered(lambda a: a.alert_type in close_types)
                if to_close:
                    to_close.write({"state": "closed", "closed_at": fields.Datetime.now()})

    @api.depends(
        "group_id",
        "group_id.active",
        "group_id.temperature_low",
        "group_id.temperature_high",
        "group_id.humidity_low",
        "group_id.humidity_high",
        "temperature_low",
        "temperature_high",
        "humidity_low",
        "humidity_high",
    )
    def _compute_effective_thresholds(self):
        for rec in self:
            t_low, t_high, h_low, h_high = rec._get_effective_threshold_values()
            rec.effective_temperature_low = t_low
            rec.effective_temperature_high = t_high
            rec.effective_humidity_low = h_low
            rec.effective_humidity_high = h_high
            rec.threshold_source = "group" if rec.group_id and rec.group_id.active else "sensor"

    def _get_effective_threshold_values(self):
        self.ensure_one()
        if self.group_id and self.group_id.active:
            return (
                self.group_id.temperature_low,
                self.group_id.temperature_high,
                self.group_id.humidity_low,
                self.group_id.humidity_high,
            )
        return (
            self.temperature_low,
            self.temperature_high,
            self.humidity_low,
            self.humidity_high,
        )
