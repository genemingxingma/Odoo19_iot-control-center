import uuid

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAttendanceRequestLogging(TransactionCase):
    def setUp(self):
        super().setUp()
        serial = f"ATT-{uuid.uuid4().hex[:12]}"
        self.device = self.env["iot.attendance.device"].create(
            {
                "name": "Sampled attendance terminal",
                "company_id": self.env.company.id,
                "protocol": "adms_http",
                "serial_number": serial,
            }
        )
        self.request_model = self.env["iot.attendance.request"]
        self.values = {
            "endpoint": "/iclock/getrequest",
            "method": "GET",
            "device_id": self.device.id,
            "serial_number": serial,
            "remote_ip": "192.0.2.10",
            "status": "matched",
            "note": "Heartbeat / getrequest",
        }

    def test_repeated_heartbeat_uses_existing_sample(self):
        first = self.request_model.create_sampled(self.values, sample_seconds=600)
        second = self.request_model.create_sampled(self.values, sample_seconds=600)

        self.assertEqual(first, second)
        self.assertEqual(
            self.request_model.search_count([("serial_number", "=", self.values["serial_number"])]),
            1,
        )

    def test_zero_sample_interval_keeps_each_request(self):
        self.request_model.create_sampled(self.values, sample_seconds=0)
        self.request_model.create_sampled(self.values, sample_seconds=0)

        self.assertEqual(
            self.request_model.search_count([("serial_number", "=", self.values["serial_number"])]),
            2,
        )

    def test_compaction_keeps_unknown_device_requests(self):
        values = dict(self.values, device_id=False, status="ignored")
        self.request_model.create([dict(values) for _index in range(3)])

        deleted = self.request_model._compact_sampled_heartbeats()

        self.assertEqual(deleted, 0)
        self.assertEqual(
            self.request_model.search_count([("serial_number", "=", self.values["serial_number"])]),
            3,
        )

    def test_compaction_preserves_one_heartbeat_per_window(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "iot_control_center.attendance_heartbeat_log_interval_seconds",
            "600",
        )
        self.request_model.create([dict(self.values) for _index in range(5)])

        deleted = self.request_model._compact_sampled_heartbeats()

        self.assertEqual(deleted, 4)
        self.assertEqual(
            self.request_model.search_count([("serial_number", "=", self.values["serial_number"])]),
            1,
        )
