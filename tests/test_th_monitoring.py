import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock

from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.tcp_service import TCPIngestService


@tagged("post_install", "-at_install")
class TestTHMonitoring(TransactionCase):
    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex[:8]
        self.gateway = self.env["iot.th.gateway"].create(
            {
                "name": f"Gateway {suffix}",
                "serial": f"GW-{suffix}",
                "company_id": self.env.company.id,
            }
        )
        self.location = self.env["stock.location"].create(
            {
                "name": f"Cold Storage {suffix}",
                "usage": "internal",
                "company_id": self.env.company.id,
            }
        )
        self.sensor = self.env["iot.th.sensor"].create(
            {
                "name": "ABCD-ch01",
                "gateway_id": self.gateway.id,
                "node_id": "ABCD",
                "probe_code": "CH01",
                "company_id": self.env.company.id,
                "location_id": self.location.id,
                "location_detail": "Refrigerator A",
            }
        )

    def _reading_values(self, reported_at=None, **overrides):
        values = {
            "sensor_id": self.sensor.id,
            "gateway_id": self.gateway.id,
            "reported_at": reported_at or fields.Datetime.now(),
            "temperature": 5.5,
            "humidity": 55.0,
        }
        values.update(overrides)
        return values

    def test_technical_name_uses_location_in_display_label(self):
        self.assertIn(self.location.name, self.sensor.display_name)
        self.assertIn("Refrigerator A", self.sensor.display_name)
        self.assertIn("ABCD-CH01", self.sensor.display_name)

    def test_ingest_does_not_overwrite_custom_sensor_name(self):
        self.sensor.name = "Primary Sample Refrigerator"
        service = TCPIngestService(self.env.cr.dbname, {})

        resolved = service._ensure_sensor(self.env, self.gateway, "abcd", "ch01")

        self.assertEqual(resolved, self.sensor)
        self.assertEqual(self.sensor.name, "Primary Sample Refrigerator")
        self.assertIn("ABCD-CH01", self.sensor.display_name)

    def test_bind_lookup_normalizes_node_and_channel_case(self):
        sensors = self.env["iot.th.sensor"].find_bind_candidates("abcd", probe_code="ch01")

        self.assertEqual(sensors, self.sensor)

    def test_timezone_aware_report_time_is_converted_to_utc(self):
        service = TCPIngestService(self.env.cr.dbname, {})

        parsed = service._parse_reported_at("2026-07-22T12:30:00+07:00")

        self.assertEqual(parsed, datetime(2026, 7, 22, 5, 30, 0))

    def test_ingest_uses_read_committed_transaction(self):
        service = TCPIngestService(self.env.cr.dbname, {})
        cursor = Mock()
        cursor.connection = Mock()

        service._configure_ingest_cursor(cursor)

        cursor.connection.set_isolation_level.assert_called_once_with(ISOLATION_LEVEL_READ_COMMITTED)

    def test_equal_timestamps_can_have_distinct_event_identities(self):
        at = fields.Datetime.now()
        first = self.env["iot.th.reading"].create(self._reading_values(at))
        second = self.env["iot.th.reading"].create(self._reading_values(at))
        self.assertNotEqual(first.event_id, second.event_id)

    def test_raw_reading_initializes_extrema_and_sample_count(self):
        reading = self.env["iot.th.reading"].create(self._reading_values())

        self.assertEqual(reading.temperature_min, reading.temperature)
        self.assertEqual(reading.temperature_max, reading.temperature)
        self.assertEqual(reading.humidity_min, reading.humidity)
        self.assertEqual(reading.humidity_max, reading.humidity)
        self.assertEqual(reading.sample_count, 1)
        self.assertEqual(self.env["iot.th.reading"]._fields["temperature"].aggregator, "avg")
        self.assertEqual(self.env["iot.th.reading"]._fields["sample_count"].aggregator, "sum")

    def test_statistics_aggregate_only_raw_samples(self):
        now = fields.Datetime.now()
        self.env["iot.th.reading"].create([
            self._reading_values(now - timedelta(minutes=i+1), temperature=10, humidity=50) for i in range(10)
        ] + [self._reading_values(now, temperature=20, humidity=70)])
        self.env.flush_all()
        self.assertAlmostEqual(self.sensor.avg_temperature, 120.0 / 11.0, places=4)
        self.assertAlmostEqual(self.sensor.avg_humidity, 570.0 / 11.0, places=4)
        self.assertEqual(self.sensor.min_temperature, 10)
        self.assertEqual(self.sensor.max_temperature, 20)
        with self.assertRaises(ValidationError):
            self.env["iot.th.reading"].create(self._reading_values(sample_count=10))

    def test_sensor_trend_action_is_scoped_to_sensor(self):
        action = self.sensor.action_open_readings()

        self.assertEqual(action["domain"], [("sensor_id", "=", self.sensor.id)])
        self.assertEqual(action["context"]["iot_time_mode"], "hour")

    def test_stale_reading_does_not_replace_latest_sensor_state(self):
        latest_at = fields.Datetime.now()
        self.sensor._apply_reading(6.0, 60.0, latest_at, battery_voltage=3.2)

        self.sensor._apply_reading(30.0, 20.0, latest_at - timedelta(hours=1), battery_voltage=2.0)

        self.assertEqual(self.sensor.last_reported_at, latest_at)
        self.assertEqual(self.sensor.last_temperature, 6.0)
        self.assertEqual(self.sensor.last_humidity, 60.0)
        self.assertEqual(self.sensor.last_battery_voltage, 3.2)
        self.assertEqual(self.sensor.reading_count, 2)
        self.assertFalse(self.env["iot.th.alert"].search([("sensor_id", "=", self.sensor.id)]))
