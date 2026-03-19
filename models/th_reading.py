from datetime import timedelta

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
    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_sensor_reported_rollup_idx
            ON iot_th_reading (sensor_id, reported_at DESC, is_daily_rollup, id DESC)
            """
        )

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
    def _cron_rollup_old_readings(self, retention_days=30, batch_size=200):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=int(retention_days))
        sensor_model = self.env["iot.th.sensor"].sudo()
        affected_sensor_ids = set()
        batch_size = max(int(batch_size), 1)

        while True:
            self.env.cr.execute(
                """
                SELECT sensor_id, bucket_day
                FROM (
                    SELECT
                        reading.sensor_id AS sensor_id,
                        date_trunc('day', reading.reported_at) AS bucket_day
                    FROM iot_th_reading reading
                    JOIN iot_th_sensor sensor ON sensor.id = reading.sensor_id
                    WHERE reading.reported_at < %s
                      AND reading.is_daily_rollup = FALSE
                      AND COALESCE(sensor.keep_full_history, FALSE) = FALSE
                    GROUP BY reading.sensor_id, date_trunc('day', reading.reported_at)
                    ORDER BY bucket_day, reading.sensor_id
                    LIMIT %s
                ) batches
                """,
                [cutoff, batch_size],
            )
            batch_rows = self.env.cr.fetchall()
            if not batch_rows:
                break

            for sensor_id, bucket_day in batch_rows:
                bucket_end = bucket_day + timedelta(days=1)
                self.env.cr.execute(
                    """
                    SELECT
                        COALESCE(MAX(reading.gateway_id), MAX(sensor.gateway_id), 0),
                        AVG(temperature),
                        AVG(humidity)
                    FROM iot_th_reading reading
                    JOIN iot_th_sensor sensor ON sensor.id = reading.sensor_id
                    WHERE reading.sensor_id = %s
                      AND reading.reported_at >= %s
                      AND reading.reported_at < %s
                      AND reading.is_daily_rollup = FALSE
                    """,
                    [sensor_id, bucket_day, bucket_end],
                )
                gateway_id, avg_temperature, avg_humidity = self.env.cr.fetchone() or (0, None, None)
                if not gateway_id or avg_temperature is None or avg_humidity is None:
                    continue

                self.env.cr.execute(
                    """
                    DELETE FROM iot_th_reading
                    WHERE sensor_id = %s
                      AND reported_at = %s
                      AND is_daily_rollup = TRUE
                    """,
                    [sensor_id, bucket_day],
                )
                self.sudo().create(
                    {
                        "sensor_id": sensor_id,
                        "gateway_id": gateway_id,
                        "reported_at": bucket_day,
                        "temperature": avg_temperature,
                        "humidity": avg_humidity,
                        "is_daily_rollup": True,
                    }
                )
                self.env.cr.execute(
                    """
                    DELETE FROM iot_th_reading
                    WHERE sensor_id = %s
                      AND reported_at >= %s
                      AND reported_at < %s
                      AND is_daily_rollup = FALSE
                    """,
                    [sensor_id, bucket_day, bucket_end],
                )
                affected_sensor_ids.add(sensor_id)

            self.env.cr.commit()

        if not affected_sensor_ids:
            return

        for sensor in sensor_model.browse(list(affected_sensor_ids)):
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
