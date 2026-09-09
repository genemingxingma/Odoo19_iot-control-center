"""Exercise the pre-migration against isolated legacy-shaped temporary tables."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestV2Cutover(TransactionCase):
    def setUp(self):
        super().setUp()
        path = Path(__file__).parents[1] / "migrations/19.0.2.0.0/pre-migration.py"
        spec = importlib.util.spec_from_file_location("iot_v2_cutover", path)
        self.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.migration)
        self.cr = self.env.cr
        # PostgreSQL resolves temporary relations ahead of public tables; no
        # installed module configuration or historical business data is touched.
        self.cr.execute("CREATE TEMP TABLE ir_config_parameter (key text, value text) ON COMMIT DROP")
        self.cr.execute("CREATE TEMP TABLE iot_th_gateway (id int, serial text, active bool, company_id int) ON COMMIT DROP")
        self.cr.execute("CREATE TEMP TABLE iot_th_sensor (id int, gateway_id int, active bool, company_id int) ON COMMIT DROP")
        self.cr.execute("CREATE TEMP TABLE iot_th_reading (id int) ON COMMIT DROP")
        self.cr.execute("CREATE TEMP TABLE iot_th_alert (id int) ON COMMIT DROP")
        self.cr.execute("INSERT INTO ir_config_parameter VALUES ('iot_control_center.v2_discard_monitoring_history', 'true')")
        self.cr.execute("INSERT INTO iot_th_gateway VALUES (1, 'registered', true, 1)")
        self.cr.execute("INSERT INTO iot_th_sensor VALUES (1, 1, true, 1)")
        self.cr.execute("INSERT INTO iot_th_reading VALUES (1), (2)")
        self.cr.execute("INSERT INTO iot_th_alert VALUES (1)")

    def _assert_blocked_without_history_loss(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            self.migration.migrate(self.cr, "19.0.1.0.19")
        self.cr.execute("SELECT count(*) FROM iot_th_reading")
        self.assertEqual(self.cr.fetchone()[0], 2)
        self.cr.execute("SELECT count(*) FROM iot_th_alert")
        self.assertEqual(self.cr.fetchone()[0], 1)
        self.cr.execute("SELECT active FROM iot_th_sensor WHERE id=1")
        self.assertTrue(self.cr.fetchone()[0])

    def test_discard_authorization_remains_required(self):
        self.cr.execute("DELETE FROM ir_config_parameter")
        self._assert_blocked_without_history_loss("explicit")

    def test_duplicate_gateway_blocks_before_destructive_work(self):
        self.cr.execute("INSERT INTO iot_th_gateway VALUES (2, 'registered', false, 1)")
        self._assert_blocked_without_history_loss("duplicate gateway identities")

    def test_unowned_gateway_blocks_without_archiving_named_probe(self):
        self.cr.execute("UPDATE iot_th_gateway SET company_id=NULL")
        self._assert_blocked_without_history_loss("without company ownership")

    def test_cross_company_probe_blocks_cutover(self):
        self.cr.execute("UPDATE iot_th_sensor SET company_id=2")
        self._assert_blocked_without_history_loss("inconsistent gateway ownership")

    def test_registered_identity_passes_preflight(self):
        self.migration._check_gateway_identities(self.cr)


@tagged("post_install", "-at_install")
class TestV2SnapshotColumnMigration(TransactionCase):
    def test_legacy_translation_metadata_and_upgrade_cache_are_retired(self):
        path = Path(__file__).parents[1] / "migrations/19.0.2.0.7/pre-migration.py"
        spec = importlib.util.spec_from_file_location("iot_snapshot_metadata_cutover", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.cr.execute("CREATE TEMP TABLE iot_th_reading (id int, sensor_location_detail jsonb) ON COMMIT DROP")
        self.cr.execute("CREATE TEMP TABLE ir_model_fields (model text, name text, translate text) ON COMMIT DROP")
        self.cr.execute("INSERT INTO ir_model_fields VALUES ('iot.th.reading', 'sensor_location_detail', 'standard'), ('iot.th.sensor', 'location_detail', 'standard')")
        self.cr.execute("""INSERT INTO iot_th_reading VALUES (1, '{"en_US":"Cold room","th_TH":"Room TH"}'), (2, '{"th_TH":"Room TH"}'), (3, NULL)""")
        cache = {'iot.th.reading.sensor_location_detail': 'standard', 'iot.th.sensor.location_detail': 'standard'}
        registry = SimpleNamespace(_database_translated_fields=cache)
        migration._migrate_snapshot(self.cr, registry)
        migration._migrate_snapshot(self.cr, registry)
        self.cr.execute("SELECT sensor_location_detail FROM iot_th_reading ORDER BY id")
        self.assertEqual(self.cr.fetchall(), [('Cold room',), ('Room TH',), (None,)])
        self.cr.execute("SELECT model, translate FROM ir_model_fields ORDER BY model")
        self.assertEqual(self.cr.fetchall(), [('iot.th.reading', None), ('iot.th.sensor', 'standard')])
        self.assertEqual(cache, {'iot.th.sensor.location_detail': 'standard'})

    def test_snapshot_registry_metadata_and_column_remain_untranslated(self):
        field = self.env['iot.th.reading']._fields['sensor_location_detail']
        self.assertFalse(field.translate)
        metadata = self.env['ir.model.fields']._get('iot.th.reading', 'sensor_location_detail')
        self.assertFalse(metadata.translate)
        self.cr.execute("SELECT atttypid::regtype::text FROM pg_attribute WHERE attrelid='iot_th_reading'::regclass AND attname='sensor_location_detail' AND NOT attisdropped")
        self.assertEqual(self.cr.fetchone()[0], 'character varying')

    def test_translated_legacy_column_becomes_writable_text_without_losing_labels(self):
        path = Path(__file__).parents[1] / "migrations/19.0.2.0.4/end-migration.py"
        spec = importlib.util.spec_from_file_location("iot_v2_snapshot_cutover", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.cr.execute("CREATE TEMP TABLE iot_th_reading (id int, sensor_location_detail jsonb) ON COMMIT DROP")
        self.cr.execute("""
            INSERT INTO iot_th_reading VALUES
            (1, '{"en_US":"Cold room","th_TH":"Room TH"}'),
            (2, '{"th_TH":"Room TH"}'), (3, NULL)
        """)
        migration.migrate(self.cr, "19.0.2.0.2")
        self.cr.execute("SELECT sensor_location_detail FROM iot_th_reading ORDER BY id")
        self.assertEqual(self.cr.fetchall(), [("Cold room",), ("Room TH",), (None,)])
        self.cr.execute("INSERT INTO iot_th_reading VALUES (4, 'New immutable snapshot')")
        migration.migrate(self.cr, "19.0.2.0.2")
        self.cr.execute("SELECT sensor_location_detail FROM iot_th_reading WHERE id=4")
        self.assertEqual(self.cr.fetchone()[0], "New immutable snapshot")
