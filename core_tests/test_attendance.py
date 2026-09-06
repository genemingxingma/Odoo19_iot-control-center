import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("attendance_core", Path(__file__).parents[1] / "core/attendance.py")
attendance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attendance)


class AttendanceProtocolTest(unittest.TestCase):
    def test_verification_never_selects_direction(self):
        for verify in ("0", "1", "2", "15"):
            for status, expected in (("0", "in"), ("1", "out")):
                row = attendance.parse_adms_line(f"23\t2026-09-06 08:00:00\t{status}\t{verify}", "ATTLOG")
                self.assertEqual(attendance.normalize_direction(row["direction"]), expected)

    def test_empty_status_does_not_shift_verify(self):
        row = attendance.parse_adms_line("23\t2026-09-06 08:00:00\t\t1", "ATTLOG")
        self.assertEqual(attendance.normalize_direction(row["direction"]), "auto")

    def test_key_value_protocol_and_pin_zero(self):
        row = attendance.parse_adms_line("PIN=0\tDateTime=2026-09-06 08:00:00\tStatus=0\tVerify=1", "ATTLOG")
        self.assertEqual(row["device_user_id"], "0")
        self.assertEqual(attendance.normalize_direction(row["direction"]), "in")
        self.assertEqual(attendance.first_value({"user_id": 0}, "user_id"), 0)

    def test_non_attendance_tables_ignored(self):
        for table in ("ATTPHOTO", "USERINFO", "OPERLOG", "BIODATA"):
            self.assertIsNone(attendance.parse_adms_line("23\t2026-09-06 08:00:00\t0\t1", table))

    def test_invalid_attendance_is_not_silently_accepted(self):
        for row in ("broken", "23\tbad-time", "\t2026-09-06 08:00:00", "23\t2026-02-30 08:00:00"):
            with self.assertRaises(ValueError):
                attendance.parse_adms_line(row, "ATTLOG")

    def test_iso_timezone_is_preserved(self):
        self.assertEqual(attendance.parse_timestamp("2026-09-06T08:00:00+07:00").utcoffset().total_seconds(), 25200)
        self.assertEqual(attendance.parse_timestamp("2026-09-06T01:00:00Z").utcoffset().total_seconds(), 0)

    def test_auto_does_not_fall_back_to_verification(self):
        self.assertEqual(attendance.normalize_direction("auto", "1"), "auto")
        self.assertEqual(attendance.normalize_direction("0", "1", "auto"), "auto")

    def test_six_device_states(self):
        self.assertEqual([attendance.normalize_direction(code) for code in range(6)],
                         ["in", "out", "out", "in", "in", "out"])
