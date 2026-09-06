from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import types
import uuid

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAttendanceReliability(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({"name": "Synthetic attendance company", "country_id": self.env.ref("base.th").id})
        self.company.partner_id.tz = "Asia/Bangkok"
        self.device = self.env["iot.attendance.device"].create({"name": "Synthetic terminal", "company_id": self.company.id,
            "serial_number": "TEST-" + uuid.uuid4().hex, "protocol": "adms_http", "host": "192.0.2.20"})
        self.employee = self.env["hr.employee"].create({"name": "Synthetic employee", "company_id": self.company.id})
        self.env["iot.attendance.user"].create({"device_id": self.device.id, "employee_id": self.employee.id, "device_user_id": "23"})

    def punches(self):
        return self.env["iot.attendance.punch"].search([("device_id", "=", self.device.id)])

    def test_direction_is_status_not_verification(self):
        self.device._ingest_adms_payload("23\t2026-09-06 08:00:00\t0\t1", "ATTLOG")
        punch = self.punches()
        self.assertEqual(punch.direction, "in")
        self.assertEqual(punch.state, "processed")
        self.assertEqual(punch.punch_time, datetime(2026, 9, 6, 1))

    def test_reversed_upload_processed_chronologically(self):
        self.assertEqual(self.device._ingest_adms_payload(
            "23\t2026-09-06 17:00:00\t1\t1\n23\t2026-09-06 08:00:00\t0\t1", "ATTLOG"), 2)
        self.assertEqual(set(self.punches().mapped("state")), {"processed"})
        records = self.punches().attendance_id
        self.assertEqual(len(records), 1)
        self.assertEqual(records.check_out - records.check_in, timedelta(hours=9))

    def test_replay_and_duplicate_rows_are_idempotent(self):
        row = "23\t2026-09-06 08:00:00\t0\t1"
        self.assertEqual(self.device._ingest_adms_payload(row + "\n" + row, "ATTLOG"), 1)
        self.assertEqual(self.device._ingest_adms_payload(row, "ATTLOG"), 0)
        self.assertEqual(len(self.punches()), 1)

    def test_invalid_batch_is_not_partially_imported(self):
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.device._ingest_adms_payload("23\t2026-09-06 08:00:00\t0\t1\nbroken", "ATTLOG")
        self.assertFalse(self.punches())

    def test_photo_metadata_is_not_attendance(self):
        self.assertEqual(self.device._ingest_adms_payload("23\t2026-09-06 08:00:00\t0\t1", "ATTPHOTO"), 0)
        self.assertFalse(self.punches())

    def test_serial_mismatch_never_uses_ip_fallback(self):
        self.assertFalse(self.device._find_adms_device("WRONG-SERIAL", remote_ip="192.0.2.20"))

    def test_employee_fallback_is_company_scoped_and_unambiguous(self):
        foreign = self.env["hr.employee"].create({"name": "Synthetic foreign employee", "company_id": self.env.company.id, "biometric_code": "99"})
        self.assertFalse(self.device._resolve_employee("99"))
        local = self.env["hr.employee"].create({"name": "Synthetic local employee", "company_id": self.company.id, "biometric_code": "99"})
        self.assertEqual(self.device._resolve_employee("99"), local)
        self.env["hr.employee"].create({"name": "Synthetic ambiguous employee", "company_id": self.company.id, "biometric_code": "99"})
        self.assertFalse(self.device._resolve_employee("99"))

    def test_cross_company_mapping_rejected(self):
        foreign = self.env["hr.employee"].create({"name": "Synthetic foreign employee", "company_id": self.env.company.id})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["iot.attendance.user"].create({"device_id": self.device.id, "employee_id": foreign.id, "device_user_id": "99"})

    def test_overlap_does_not_lose_other_employees_punches(self):
        self.env["hr.attendance"].create({"employee_id": self.employee.id,
            "check_in": datetime(2026, 9, 6, 1), "check_out": datetime(2026, 9, 6, 5)})
        other = self.env["hr.employee"].create({"name": "Synthetic second employee", "company_id": self.company.id, "biometric_code": "24"})
        self.device._ingest_adms_payload("23\t2026-09-06 10:00:00\t0\t1\n24\t2026-09-06 10:00:00\t0\t1", "ATTLOG")
        self.assertEqual(self.punches().filtered(lambda p: p.employee_id == self.employee).error_code, "processing_error")
        self.assertEqual(self.punches().filtered(lambda p: p.employee_id == other).state, "processed")

    def test_paused_device_does_not_process_upload(self):
        self.device.sync_enabled = False
        with self.assertRaises(UserError):
            self.device._ingest_adms_payload("23\t2026-09-06 08:00:00\t0\t1", "ATTLOG")
        self.assertFalse(self.punches())

    def test_timezone_aware_timestamp(self):
        self.assertEqual(self.device._parse_device_datetime("2026-09-06T08:00:00+07:00"), datetime(2026, 9, 6, 1))

    def test_internal_http_url_does_not_invent_tls(self):
        self.company.write({"iot_internal_host": "192.0.2.30", "iot_internal_odoo_port": 18069})
        self.assertEqual(self.device.adms_http_url, "http://192.0.2.30:18069")
        self.assertFalse(self.device.adms_https_url)

    def test_pull_does_not_clear_uncommitted_device_records(self):
        connection = MagicMock()
        connection.get_attendance.return_value = [types.SimpleNamespace(user_id="23", uid=1,
            timestamp=datetime(2026, 9, 6, 8), status=1, punch=0)]
        zk = types.SimpleNamespace(ZK=MagicMock())
        zk.ZK.return_value.connect.return_value = connection
        self.device.auto_clear_after_sync = True
        with patch.dict("sys.modules", {"zk": zk}):
            self.assertEqual(len(self.device._fetch_zk_punches()), 1)
        connection.clear_attendance.assert_not_called()
        connection.enable_device.assert_called_once()

    def test_overview_respects_selected_company(self):
        overview = self.env["iot.control.board"].with_context(allowed_company_ids=[self.company.id]).get_overview()
        card = next(card for card in overview["cards"] if card["key"] == "attendance")
        self.assertEqual(card["total"], 1)
        self.assertEqual(card["offline"], 1)
        self.assertEqual(overview["companies"], [self.company.name])

    def test_overview_count_links_match_their_metrics(self):
        self.env["iot.device"].create([
            {"name": "Synthetic connected relay", "serial": "LINK-" + uuid.uuid4().hex,
             "company_id": self.company.id, "last_seen": datetime.now()},
            {"name": "Synthetic silent relay", "serial": "LINK-" + uuid.uuid4().hex,
             "company_id": self.company.id}])
        overview = self.env["iot.control.board"].with_context(allowed_company_ids=[self.company.id]).get_overview()
        for card in overview["cards"]:
            for action_key, count_key in (("action", "total"), ("attention_action", "offline"),
                                          ("secondary_action", "secondary_count")):
                action = card[action_key]
                self.assertEqual(self.env[action["res_model"]].search_count(action["domain"]), card[count_key])

    def test_sync_summary_has_a_translatable_display(self):
        self.device.last_sync_message = "ADMS received 7 punch(es)."
        self.assertIn("7", self.device.display_last_sync_message)
        self.device.last_sync_message = "Diagnostic message"
        self.assertEqual(self.device.display_last_sync_message, "Diagnostic message")
