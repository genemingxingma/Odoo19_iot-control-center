import logging
from datetime import timedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class IoTTHReading(models.Model):
    _name = "iot.th.reading"
    _description = "Temperature/Humidity Reading"
    _order = "reported_at desc, id desc"

    sensor_id = fields.Many2one("iot.th.sensor", required=True, index=True, ondelete="cascade")
    sensor_code = fields.Char(related="sensor_id.probe_code", string="Sensor Channel", store=True, index=True)
    gateway_id = fields.Many2one("iot.th.gateway", required=True, index=True, ondelete="cascade")
    node_id = fields.Char(related="sensor_id.node_id", string="Node ID", store=True, index=True)
    company_id = fields.Many2one(related="sensor_id.company_id", store=True, index=True)
    sensor_location_id = fields.Many2one(
        related="sensor_id.location_id",
        string="Sensor Location",
        store=True,
        index=True,
    )
    sensor_location_detail = fields.Char(
        related="sensor_id.location_detail",
        string="Location Detail",
        store=True,
    )
    sensor_group_id = fields.Many2one(
        related="sensor_id.group_id",
        string="Sensor Group",
        store=True,
        index=True,
    )

    reported_at = fields.Datetime(required=True, index=True)
    is_hourly_rollup = fields.Boolean(
        string="Hourly Rollup",
        default=False,
        index=True,
        help="Generated hourly aggregate for historical data retention.",
    )
    is_daily_rollup = fields.Boolean(
        string="Daily Rollup",
        default=False,
        index=True,
        help="Generated daily aggregate for historical data retention.",
    )
    temperature = fields.Float(
        string="Temperature (C)",
        required=True,
        digits=(16, 2),
        aggregator="avg",
    )
    humidity = fields.Float(
        string="Relative Humidity (%RH)",
        required=True,
        digits=(16, 2),
        aggregator="avg",
    )
    temperature_min = fields.Float(
        string="Minimum Temperature (C)",
        digits=(16, 2),
        aggregator="min",
    )
    temperature_max = fields.Float(
        string="Maximum Temperature (C)",
        digits=(16, 2),
        aggregator="max",
    )
    humidity_min = fields.Float(
        string="Minimum Humidity (%RH)",
        digits=(16, 2),
        aggregator="min",
    )
    humidity_max = fields.Float(
        string="Maximum Humidity (%RH)",
        digits=(16, 2),
        aggregator="max",
    )
    sample_count = fields.Integer(default=1, string="Sample Count", aggregator="sum")

    @api.model
    def init(self):
        self.env.cr.execute("UPDATE iot_th_sensor SET reading_count = 0")
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_sensor_reported_rollup_idx
            ON iot_th_reading (sensor_id, reported_at DESC, is_hourly_rollup, is_daily_rollup, id DESC)
            """
        )
        self.env.cr.execute(
            """
            UPDATE iot_th_reading
               SET temperature_min = COALESCE(temperature_min, temperature),
                   temperature_max = COALESCE(temperature_max, temperature),
                   humidity_min = COALESCE(humidity_min, humidity),
                   humidity_max = COALESCE(humidity_max, humidity),
                   sample_count = GREATEST(COALESCE(sample_count, 1), 1)
            WHERE temperature_min IS NULL
               OR temperature_max IS NULL
               OR humidity_min IS NULL
               OR humidity_max IS NULL
               OR sample_count IS NULL
               OR sample_count < 1
            """
        )
        # Older deployments accepted the same gateway frame more than once.
        # Keep the latest audit row before adding an idempotency index.
        self.env.cr.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            sensor_id,
                            reported_at,
                            COALESCE(is_hourly_rollup, FALSE),
                            COALESCE(is_daily_rollup, FALSE)
                        ORDER BY create_date DESC NULLS LAST, id DESC
                    ) AS row_number
                FROM iot_th_reading
            )
            DELETE FROM iot_th_reading reading
            USING ranked
            WHERE reading.id = ranked.id
              AND ranked.row_number > 1
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS iot_th_reading_identity_uniq
            ON iot_th_reading (
                sensor_id,
                reported_at,
                COALESCE(is_hourly_rollup, FALSE),
                COALESCE(is_daily_rollup, FALSE)
            )
            """
        )
        self.env.cr.execute(
            """
            UPDATE iot_th_sensor sensor
               SET reading_count = counts.reading_count
              FROM (
                  SELECT
                      sensor_id,
                      SUM(GREATEST(COALESCE(sample_count, 1), 1)) AS reading_count
                  FROM iot_th_reading
                  GROUP BY sensor_id
              ) counts
             WHERE sensor.id = counts.sensor_id
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_company_reported_sensor_idx
            ON iot_th_reading (company_id, reported_at DESC, sensor_id, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_graph_raw_idx
            ON iot_th_reading (company_id, reported_at DESC, sensor_id, id DESC)
            WHERE COALESCE(is_hourly_rollup, FALSE) = FALSE
              AND COALESCE(is_daily_rollup, FALSE) = FALSE
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_graph_hourly_idx
            ON iot_th_reading (company_id, reported_at DESC, sensor_id, id DESC)
            WHERE COALESCE(is_hourly_rollup, FALSE) = TRUE
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS iot_th_reading_graph_daily_idx
            ON iot_th_reading (company_id, reported_at DESC, sensor_id, id DESC)
            WHERE COALESCE(is_daily_rollup, FALSE) = TRUE
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
        created = self.browse()
        for vals in vals_list:
            values = dict(vals)
            t = values.get("temperature")
            h = values.get("humidity")
            if t is not None and h is not None and self._is_invalid_zero_pair(t, h):
                continue
            if t is not None:
                values.setdefault("temperature_min", t)
                values.setdefault("temperature_max", t)
            if h is not None:
                values.setdefault("humidity_min", h)
                values.setdefault("humidity_max", h)
            values["sample_count"] = max(int(values.get("sample_count") or 1), 1)

            sensor_id = values.get("sensor_id")
            reported_at = fields.Datetime.to_datetime(values.get("reported_at"))
            if sensor_id and reported_at:
                is_hourly = bool(values.get("is_hourly_rollup", False))
                is_daily = bool(values.get("is_daily_rollup", False))
                identity = f"{sensor_id}|{fields.Datetime.to_string(reported_at)}|{int(is_hourly)}|{int(is_daily)}"
                self.env.cr.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    [f"iot.th.reading:{identity}"],
                )
                existing = self.sudo().search(
                    [
                        ("sensor_id", "=", sensor_id),
                        ("reported_at", "=", reported_at),
                        ("is_hourly_rollup", "=", is_hourly),
                        ("is_daily_rollup", "=", is_daily),
                    ],
                    limit=1,
                )
                if existing:
                    if t is not None and h is not None and (
                        abs(existing.temperature - float(t)) > 1e-9
                        or abs(existing.humidity - float(h)) > 1e-9
                    ):
                        _logger.warning(
                            "Conflicting duplicate TH reading ignored for sensor %s at %s",
                            sensor_id,
                            reported_at,
                        )
                    continue
            created |= super().create([values])
        return created

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
        safe_domain = fields.Domain.AND(
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
    def _cron_rollup_old_readings(self, retention_days=None, batch_size=500):
        icp = self.env["ir.config_parameter"].sudo()
        if retention_days is None:
            retention_days = icp.get_param("iot_control_center.th_raw_retention_days", "30")
        try:
            retention_days = max(int(retention_days or 30), 1)
        except Exception:
            retention_days = 30
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=retention_days)
        cutoff_day = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
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
                      AND COALESCE(reading.is_daily_rollup, FALSE) = FALSE
                      AND COALESCE(sensor.keep_full_history, FALSE) = FALSE
                      AND (reading.temperature <> 0 OR reading.humidity <> 0)
                    GROUP BY reading.sensor_id, date_trunc('day', reading.reported_at)
                    ORDER BY bucket_day, reading.sensor_id
                    LIMIT %s
                ) batches
                """,
                    [cutoff_day, batch_size],
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
                        SUM(temperature * GREATEST(COALESCE(sample_count, 1), 1))
                            / NULLIF(SUM(GREATEST(COALESCE(sample_count, 1), 1)), 0),
                        SUM(humidity * GREATEST(COALESCE(sample_count, 1), 1))
                            / NULLIF(SUM(GREATEST(COALESCE(sample_count, 1), 1)), 0),
                        MIN(COALESCE(temperature_min, temperature)),
                        MAX(COALESCE(temperature_max, temperature)),
                        MIN(COALESCE(humidity_min, humidity)),
                        MAX(COALESCE(humidity_max, humidity)),
                        SUM(GREATEST(COALESCE(sample_count, 1), 1))
                    FROM iot_th_reading reading
                    JOIN iot_th_sensor sensor ON sensor.id = reading.sensor_id
                    WHERE reading.sensor_id = %s
                      AND reading.reported_at >= %s
                      AND reading.reported_at < %s
                       AND COALESCE(reading.is_daily_rollup, FALSE) = FALSE
                       AND (
                           COALESCE(reading.is_hourly_rollup, FALSE) = FALSE
                           OR NOT EXISTS (
                               SELECT 1
                               FROM iot_th_reading raw
                               WHERE raw.sensor_id = reading.sensor_id
                                 AND raw.reported_at >= date_trunc('day', reading.reported_at)
                                 AND raw.reported_at < date_trunc('day', reading.reported_at) + INTERVAL '1 day'
                                 AND COALESCE(raw.is_hourly_rollup, FALSE) = FALSE
                                 AND COALESCE(raw.is_daily_rollup, FALSE) = FALSE
                                 AND (raw.temperature <> 0 OR raw.humidity <> 0)
                           )
                       )
                       AND (reading.temperature <> 0 OR reading.humidity <> 0)
                    """,
                    [sensor_id, bucket_day, bucket_end],
                )
                (
                    gateway_id,
                    avg_temperature,
                    avg_humidity,
                    min_temperature,
                    max_temperature,
                    min_humidity,
                    max_humidity,
                    sample_count,
                ) = self.env.cr.fetchone() or (0, None, None, None, None, None, None, 0)
                if not gateway_id or avg_temperature is None or avg_humidity is None:
                    continue

                self.env.cr.execute(
                    """
                    DELETE FROM iot_th_reading
                    WHERE sensor_id = %s
                      AND reported_at = %s
                      AND COALESCE(is_hourly_rollup, FALSE) = TRUE
                    """,
                    [sensor_id, bucket_day],
                )
                self.env.cr.execute(
                    """
                    DELETE FROM iot_th_reading
                    WHERE sensor_id = %s
                      AND reported_at = %s
                      AND COALESCE(is_daily_rollup, FALSE) = TRUE
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
                        "temperature_min": min_temperature,
                        "temperature_max": max_temperature,
                        "humidity_min": min_humidity,
                        "humidity_max": max_humidity,
                        "sample_count": sample_count,
                        "is_hourly_rollup": False,
                        "is_daily_rollup": True,
                    }
                )
                self.env.cr.execute(
                    """
                    DELETE FROM iot_th_reading
                    WHERE sensor_id = %s
                      AND reported_at >= %s
                      AND reported_at < %s
                      AND COALESCE(is_daily_rollup, FALSE) = FALSE
                    """,
                    [sensor_id, bucket_day, bucket_end],
                )
                affected_sensor_ids.add(sensor_id)

            self.env.cr.commit()

        if not affected_sensor_ids:
            return

        for sensor in sensor_model.browse(list(affected_sensor_ids)):
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(GREATEST(COALESCE(sample_count, 1), 1)), 0)
                FROM iot_th_reading
                WHERE sensor_id = %s
                """,
                [sensor.id],
            )
            vals = {"reading_count": self.env.cr.fetchone()[0]}
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
