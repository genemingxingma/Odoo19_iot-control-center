from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class IoTTHSensor(models.Model):
    _name = "iot.th.sensor"
    _description = "Node Sensor Channel (Temp+Humidity)"
    _rec_names_search = ["name", "technical_code", "node_id", "probe_code", "location_detail"]

    name = fields.Char(
        string="Probe Name",
        required=True,
        help="Friendly name used in charts; the technical code is stored separately.",
    )
    probe_code = fields.Char(string="Sensor Channel", required=True, index=True)
    technical_code = fields.Char(compute="_compute_technical_code", store=True, index=True)
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
    online = fields.Boolean(compute="_compute_online")
    reading_count = fields.Integer(string="Sample Count", default=0)

    stats_window_hours = fields.Integer(default=24)
    keep_full_history = fields.Boolean(
        string="Keep Full History",
        default=False,
        help="If enabled, this node keeps all raw readings and skips historical daily rollup.",
    )
    avg_temperature = fields.Float(compute="_compute_stats")
    avg_humidity = fields.Float(compute="_compute_stats")
    min_temperature = fields.Float(compute="_compute_stats")
    max_temperature = fields.Float(compute="_compute_stats")
    min_humidity = fields.Float(compute="_compute_stats")
    max_humidity = fields.Float(compute="_compute_stats")

    reading_ids = fields.One2many("iot.th.reading", "sensor_id")

    _node_probe_uniq = models.Constraint(
        "UNIQUE(node_id, probe_code)",
        "Sensor Channel must be unique by Node ID + Channel.",
    )

    @api.depends("node_id", "probe_code")
    def _compute_technical_code(self):
        for rec in self:
            parts = [part for part in ((rec.node_id or "").strip(), (rec.probe_code or "").strip()) if part]
            rec.technical_code = "-".join(parts)

    @api.depends("name", "technical_code", "location_id.name", "location_detail")
    @api.depends_context("lang")
    def _compute_display_name(self):
        for rec in self:
            technical = (rec.technical_code or "").strip()
            configured_name = (rec.name or "").strip()
            canonical_names = {
                technical.casefold(),
                f"{(rec.node_id or '').strip()}-{(rec.probe_code or '').strip().lower()}".casefold(),
            }
            if configured_name and configured_name.casefold() not in canonical_names:
                label = configured_name
            else:
                location = rec.location_id.name if rec.location_id else ""
                detail = (rec.location_detail or "").strip()
                label = " / ".join(part for part in (location, detail) if part) or configured_name or technical
            if technical and technical.casefold() not in label.casefold():
                label = f"{label} [{technical}]"
            rec.display_name = label or _("Unnamed Sensor")

    @api.depends("last_reported_at")
    def _compute_online(self):
        timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.th_online_timeout_sec", 300))
        now = fields.Datetime.now()
        for rec in self:
            rec.online = bool(rec.last_reported_at and (now - rec.last_reported_at) <= timedelta(seconds=timeout))

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
        nid = (node_id or "").strip().upper()
        if not nid:
            raise UserError(_("Node ID is required"))
        domain = [("node_id", "=", nid)]
        probe = (probe_code or "").strip().upper()
        if probe:
            domain.append(("probe_code", "=", probe))
        sensors = self.sudo().search(domain, order="last_reported_at desc, id desc")
        if not sensors:
            raise UserError(_("No sensor found for this Node ID."))
        if require_online:
            timeout = int(self.env["ir.config_parameter"].sudo().get_param("iot_control_center.th_online_timeout_sec", 300))
            now = fields.Datetime.now()
            offline = sensors.filtered(lambda s: not s.last_reported_at or (now - s.last_reported_at) > timedelta(seconds=timeout))
            if offline:
                if len(sensors) == 1:
                    raise UserError(_("Node is offline. Please wait for fresh data before binding."))
                sensors = sensors - offline
                if not sensors:
                    raise UserError(_("All matched sensors are offline. Please wait for fresh data before binding."))
        return sensors.sudo()

    @api.model
    def bind_by_node(self, node_id, probe_code=None, company=None, location=None, location_detail=None):
        sensors = self.find_bind_candidates(node_id, probe_code=probe_code, require_online=True)
        target_company = company or self.env.company
        conflict = sensors.filtered(lambda s: s.company_id and s.company_id != target_company)
        if conflict:
            raise UserError(_("This node is already bound to another company."))
        vals = {"company_id": target_company.id}
        if location:
            vals["location_id"] = location.id
        if location_detail is not None:
            vals["location_detail"] = location_detail
        sensors.write(vals)
        return sensors.with_env(self.env)

    def action_unbind(self):
        self.write({"company_id": False, "group_id": False, "location_id": False, "location_detail": False})

    def action_open_readings(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("iot_control_center.action_iot_th_reading")
        action.update(
            {
                "name": _("Trend - %s") % self.display_name,
                "domain": [("sensor_id", "=", self.id)],
                "context": {
                    "graph_mode": "line",
                    "graph_measure": "temperature",
                    "graph_stacked": False,
                    "graph_cumulated": False,
                    "iot_time_mode": "hour",
                    "search_default_iot_hourly_avg": 1,
                    "search_default_iot_last_5_days": 1,
                },
            }
        )
        return action

    @api.depends("last_reported_at", "stats_window_hours")
    def _compute_stats(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.avg_temperature = 0.0
            rec.avg_humidity = 0.0
            rec.min_temperature = 0.0
            rec.max_temperature = 0.0
            rec.min_humidity = 0.0
            rec.max_humidity = 0.0

        by_window = {}
        for rec in self:
            window = max(rec.stats_window_hours or 24, 1)
            by_window.setdefault(window, self.env["iot.th.sensor"])
            by_window[window] |= rec

        for window, records in by_window.items():
            since = now - timedelta(hours=window)
            self.env.cr.execute(
                """
                SELECT
                    sensor_id,
                    SUM(temperature * GREATEST(COALESCE(sample_count, 1), 1))
                        / NULLIF(SUM(GREATEST(COALESCE(sample_count, 1), 1)), 0),
                    MIN(COALESCE(temperature_min, temperature)),
                    MAX(COALESCE(temperature_max, temperature)),
                    SUM(humidity * GREATEST(COALESCE(sample_count, 1), 1))
                        / NULLIF(SUM(GREATEST(COALESCE(sample_count, 1), 1)), 0),
                    MIN(COALESCE(humidity_min, humidity)),
                    MAX(COALESCE(humidity_max, humidity))
                FROM iot_th_reading
                WHERE sensor_id = ANY(%s)
                  AND reported_at >= %s
                  AND (temperature <> 0 OR humidity <> 0)
                  AND COALESCE(is_hourly_rollup, FALSE) = FALSE
                GROUP BY sensor_id
                """,
                [records.ids, since],
            )
            rows = {row[0]: row[1:] for row in self.env.cr.fetchall()}
            for rec in records:
                avg_t, min_t, max_t, avg_h, min_h, max_h = rows.get(rec.id, (None, None, None, None, None, None))
                if avg_t is None and avg_h is None:
                    continue
                rec.avg_temperature = avg_t or 0.0
                rec.min_temperature = min_t or 0.0
                rec.max_temperature = max_t or 0.0
                rec.avg_humidity = avg_h or 0.0
                rec.min_humidity = min_h or 0.0
                rec.max_humidity = max_h or 0.0

    @api.constrains("company_id", "group_id")
    def _check_group_company(self):
        for rec in self:
            if rec.group_id and rec.company_id and rec.group_id.company_id and rec.group_id.company_id != rec.company_id:
                raise UserError(_("Sensor Group company must match the sensor company."))

    @api.constrains("temperature_low", "temperature_high", "humidity_low", "humidity_high", "stats_window_hours")
    def _check_thresholds(self):
        for rec in self:
            if rec.temperature_low > rec.temperature_high:
                raise ValidationError(_("Temperature low limit must not exceed high limit."))
            if rec.humidity_low > rec.humidity_high:
                raise ValidationError(_("Humidity low limit must not exceed high limit."))
            if rec.stats_window_hours <= 0:
                raise ValidationError(_("Statistics window must be greater than 0 hours."))

    def apply_reading(self, temperature, humidity, reported_at, battery_voltage=None):
        alert_model = self.env["iot.th.alert"]
        for rec in self:
            self.env.cr.execute(
                "UPDATE iot_th_sensor SET reading_count = COALESCE(reading_count, 0) + 1 WHERE id = %s",
                [rec.id],
            )
            rec.invalidate_recordset(["reading_count"])
            if rec.last_reported_at and reported_at < rec.last_reported_at:
                continue
            rec.last_temperature = temperature
            rec.last_humidity = humidity
            if battery_voltage is not None:
                rec.last_battery_voltage = battery_voltage
            rec.last_reported_at = reported_at

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
