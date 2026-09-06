"""Synthetic HTTP regression tests, including actual Odoo request dispatch."""
import uuid

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestAttendanceHTTP(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.serial = "HTTP-TEST-" + uuid.uuid4().hex
        cls.company = cls.env["res.company"].create({
            "name": "Synthetic HTTP company", "country_id": cls.env.ref("base.th").id})
        cls.company.partner_id.tz = "Asia/Bangkok"
        cls.device = cls.env["iot.attendance.device"].create({
            "name": "Synthetic HTTP terminal", "company_id": cls.company.id,
            "serial_number": cls.serial, "protocol": "adms_http"})

    def upload(self, body, path="/iclock/cdata", **kwargs):
        return self.url_open(path, params={"SN": self.serial, "table": "ATTLOG"},
            data=body, headers={"Content-Type": kwargs.get("content_type", "text/plain")})

    def punches(self):
        self.env.invalidate_all()
        return self.env["iot.attendance.punch"].search([("device_id", "=", self.device.id)])

    def test_valid_and_replay(self):
        row = "999\t2026-09-06 08:00:00\t0\t1"
        for _ in range(2):
            response = self.upload(row)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "OK")
        self.assertEqual(len(self.punches()), 1)
        self.assertEqual(self.punches().error_code, "no_employee_mapping")
        log = self.env["iot.attendance.request"].search([("device_id", "=", self.device.id)])
        self.assertTrue(log)
        self.assertFalse(any(log.mapped("payload_text")))

    def test_malformed_batch_rolls_back_and_is_not_acknowledged(self):
        for path in ("/iclock/cdata", "/iclock/legacy-upload"):
            response = self.upload("999\t2026-09-06 08:00:00\t0\t1\nbroken", path=path)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.text, "ERROR")
            self.assertFalse(self.punches())

    def test_oversized_upload(self):
        response = self.upload("x" * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.punches())

    def test_consumed_form_body_is_not_silently_acknowledged(self):
        response = self.upload("999\t2026-09-06 08:00:00\t0\t1", content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.punches())

    def test_denied_source_is_not_acknowledged(self):
        self.env["ir.config_parameter"].sudo().set_param("iot_control_center.attendance_allowed_ips", "192.0.2.1")
        response = self.upload("999\t2026-09-06 08:00:00\t0\t1")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.punches())

    def test_unknown_serial_is_not_acknowledged(self):
        response = self.url_open("/iclock/cdata", params={"SN": "UNKNOWN-TEST", "table": "ATTLOG"},
            data="999\t2026-09-06 08:00:00\t0\t1", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.punches())
