"""Synthetic offline validation of heater update evidence; never opens a port."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import flash_heater_release as flash


class HeaterFlashEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"image_sha256": "a" * 64, "firmware": "3.2.0-rc7",
            "expected_mac": "02:00:00:00:00:01", "sensor_rom": "280102030405069E"}
        self.receipt = {"candidate_sha256": "a" * 64, "data_region_unchanged": True,
            "phase": "write_hash_verified_awaiting_runtime"}
        sample = {"firmware": "3.2.0-rc7", "device_id": "HTR-020000000001", "enabled": False,
            "output": False, "detected_sensor_count": 1, "detected_sensor_rom": self.manifest["sensor_rom"],
            "storage": True, "journal_healthy": True, "display_ready": True, "temperature_valid": True,
            "probe_matches_binding": True, "probe_external_power": True, "probe_scratchpad_valid": True,
            "loop_fault_this_boot": False, "loop_trip_gap_ms": 0, "probe_crc_error": False,
            "fault": "loop_stalled", "loop_fault_restored": True, "probe_scan_count": 2}
        sample.update(settings_ready=True, temperature_record_interval_s=3600, setpoint_source="default", target=42)
        self.samples = [dict(sample, uptime_ms=t) for t in (1000, 31000, 65000)]

    def test_retained_historical_fault_is_not_a_new_stall(self):
        flash.verify_runtime(self.manifest, self.samples, self.receipt)

    def test_rejects_incomplete_or_unsafe_evidence(self):
        for field, bad in (("enabled", True), ("output", True), ("detected_sensor_count", 0),
            ("probe_external_power", False), ("loop_fault_this_boot", True), ("probe_crc_error", True),
            ("loop_trip_gap_ms", 1001), ("loop_fault_restored", False), ("probe_scan_count", 1),
            ("target", 37), ("temperature_record_interval_s", 60), ("settings_ready", False),
            ("temperature_valid", False), ("detected_sensor_rom", "2800000000000000")):
            with self.subTest(field=field):
                samples = copy.deepcopy(self.samples); samples[-1][field] = bad
                with self.assertRaises(ValueError): flash.verify_runtime(self.manifest, samples, self.receipt)
        for field, bad in (("candidate_sha256", "b" * 64), ("data_region_unchanged", False), ("phase", "failed")):
            with self.subTest(field=field):
                with self.assertRaises(ValueError): flash.verify_runtime(self.manifest, self.samples, dict(self.receipt, **{field: bad}))

    def test_rejects_short_or_rebooted_observation(self):
        samples = copy.deepcopy(self.samples); samples[-1]["uptime_ms"] = 500
        with self.assertRaises(ValueError): flash.verify_runtime(self.manifest, samples, self.receipt)

    def test_device_metadata_must_not_be_in_repository(self):
        with self.assertRaises(ValueError): flash.external_path(flash.ROOT / "device.json")

    def test_flash_keeps_one_session_and_checks_data_before_startup(self):
        order = []; data = bytes(flash.FLASH_BYTES)
        class Stub:
            sync_stub_detected = True
            _port = SimpleNamespace(close=lambda: order.append("close"))
            def read_mac(self): return (2, 0, 0, 0, 0, 1)
            def run_stub(self): order.append("stub"); return self
            def flash_id(self): return 0x160000
            def change_baud(self, value): order.append(("baud", value))
            def read_flash(self, start, size, progress): order.append("backup"); return data
            def sync(self): order.append("sync")
            def flash_md5sum(self, start, size):
                order.append("full_hash" if start == 0 else "retained_hash"); return hashlib.md5(data[start:start+size]).hexdigest()
            def soft_reset(self, _): order.append("startup")
        stub = Stub()
        def connect(*args, **kwargs): order.append("connect"); return stub
        fake = SimpleNamespace(get_default_connected_device=connect,
            main=lambda args, esp: order.append("write"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "image.bin"; candidate.write_bytes(b"fixture")
            m = dict(self.manifest, backup_sha256="b" * 64, candidate=candidate,
                receipt=root / "receipt.json", preflash_backup=root / "backup.bin")
            args = SimpleNamespace(esptool_dir=root, port="MOCK", connect_attempts=1,
                connect_baud=115200, baud=115200)
            with patch("builtins.print"), patch.dict("sys.modules", {"esptool": fake, "esptool.cmds": SimpleNamespace(DETECTED_FLASH_SIZES={0x16: "4MB"})}):
                flash.flash(m, args)
            self.assertEqual(order, ["connect", "stub", ("baud", 115200), "backup", "full_hash", "sync", "write", "retained_hash", "startup", "close"])
            receipt = json.loads(m["receipt"].read_text())
            self.assertTrue(receipt["data_region_unchanged"])
            self.assertEqual(receipt["phase"], "write_hash_verified_awaiting_runtime")


if __name__ == "__main__": unittest.main()
