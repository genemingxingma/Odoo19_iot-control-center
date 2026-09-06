"""Exercise the pre-migration against isolated legacy-shaped temporary tables."""
import importlib.util
from pathlib import Path

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
