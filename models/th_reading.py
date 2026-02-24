from odoo import api, fields, models
from odoo.osv import expression


class IoTTHReading(models.Model):
    _name = "iot.th.reading"
    _description = "Temperature/Humidity Reading"
    _order = "reported_at desc, id desc"

    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="cascade")
    sensor_code = fields.Char(related="sensor_id.probe_code", string="Sensor Channel", store=True, index=True)
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="cascade")
    node_id = fields.Char(related="sensor_id.node_id", string="Node ID", store=True, index=True)
    company_id = fields.Many2one(related="sensor_id.company_id", store=True, index=True)

    reported_at = fields.Datetime(required=True, index=True)
    is_daily_rollup = fields.Boolean(
        string="Daily Rollup",
        default=False,
        index=True,
        help="Generated daily aggregate for historical data retention.",
    )
    temperature = fields.Float(required=True)
    humidity = fields.Float(required=True)

    @api.model
    def _is_invalid_zero_pair(self, temperature, humidity):
        try:
            t = float(temperature)
            h = float(humidity)
        except Exception:
            return False
        return abs(t) < 1e-9 and abs(h) < 1e-9

    @api.model_create_multi
    def create(self, vals_list):
        filtered = []
        for vals in vals_list:
            t = vals.get("temperature")
            h = vals.get("humidity")
            if t is not None and h is not None and self._is_invalid_zero_pair(t, h):
                continue
            filtered.append(vals)
        if not filtered:
            return self.browse()
        return super().create(filtered)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        for fname in ("temperature", "humidity"):
            if fname in result:
                result[fname]["aggregator"] = "avg"
        return result

    def _force_avg_measures(self, field_specs):
        normalized = []
        for spec in field_specs or []:
            if spec == "temperature":
                normalized.append("temperature:avg")
            elif spec == "humidity":
                normalized.append("humidity:avg")
            elif isinstance(spec, str) and spec.startswith("temperature:"):
                normalized.append("temperature:avg")
            elif isinstance(spec, str) and spec.startswith("humidity:"):
                normalized.append("humidity:avg")
            else:
                normalized.append(spec)
        return normalized

    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        safe_domain = expression.AND(
            [
                domain or [],
                ["|", ("temperature", "!=", 0.0), ("humidity", "!=", 0.0)],
            ]
        )
        return super().read_group(
            safe_domain,
            self._force_avg_measures(fields),
            groupby,
            offset=offset,
            limit=limit,
            orderby=orderby,
            lazy=lazy,
        )

    @api.model
    def _cron_rollup_old_readings(self, retention_days=30):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=int(retention_days))
        source_domain = [
            ("reported_at", "<", cutoff),
            ("is_daily_rollup", "=", False),
            ("sensor_id.keep_full_history", "=", False),
        ]
        source_rows = self.sudo().search(source_domain)
        if not source_rows:
            return

        grouped = self.sudo().read_group(
            source_domain,
            ["temperature:avg", "humidity:avg", "sensor_id", "reported_at:day"],
            ["sensor_id", "reported_at:day"],
            lazy=False,
        )

        sensor_model = self.env["iot.th.sensor"].sudo()
        sensor_ids = [g["sensor_id"][0] for g in grouped if g.get("sensor_id")]
        sensors = sensor_model.browse(sensor_ids)
        gateway_by_sensor = {s.id: s.gateway_id.id for s in sensors}

        rollup_vals = []
        for g in grouped:
            sensor = g.get("sensor_id")
            day_label = g.get("reported_at:day")
            if not sensor or not day_label:
                continue
            sensor_id = sensor[0]
            gateway_id = gateway_by_sensor.get(sensor_id)
            if not gateway_id:
                continue
            rollup_vals.append(
                {
                    "sensor_id": sensor_id,
                    "gateway_id": gateway_id,
                    "reported_at": day_label,
                    "temperature": g.get("temperature") or 0.0,
                    "humidity": g.get("humidity") or 0.0,
                    "is_daily_rollup": True,
                }
            )

        source_rows.unlink()
        if rollup_vals:
            self.sudo().create(rollup_vals)

        # Keep sensor counters/last values consistent after compression.
        for sensor in sensors:
            vals = {"reading_count": self.sudo().search_count([("sensor_id", "=", sensor.id)])}
            last = self.sudo().search([("sensor_id", "=", sensor.id)], order="reported_at desc, id desc", limit=1)
            if last:
                vals.update(
                    {
                        "last_temperature": last.temperature,
                        "last_humidity": last.humidity,
                        "last_reported_at": last.reported_at,
                    }
                )
            sensor.write(vals)
