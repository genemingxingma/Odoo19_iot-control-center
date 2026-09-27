"""Offline transport guard tests; importing this module never opens a port."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("washer_probe", ROOT / "tools/probe_washer_usb_screen.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class FakePort:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, count):
        if not self.chunks:
            return b""
        chunk = self.chunks[0][:count]
        self.chunks[0] = self.chunks[0][count:]
        if not self.chunks[0]:
            self.chunks.pop(0)
        return chunk


class TransportTests(unittest.TestCase):
    def test_fragmented_marker(self):
        self.assertEqual(probe.read_until(FakePort([b"junkOK", b"AY"]), b"OKAY"), b"junkOKAY")

    def test_bridge_error_precedes_success(self):
        with self.assertRaises(RuntimeError):
            probe.read_until(FakePort([probe.ERROR + b"OK"]), b"OK")

    def test_bounded_input(self):
        with self.assertRaises(TimeoutError):
            probe.read_until(FakePort([b"x" * 1024]), b"OK", limit=100)

    def test_deadline(self):
        with patch.object(probe.time, "monotonic", side_effect=[0, 0, 4]):
            with self.assertRaises(TimeoutError):
                probe.read_until(FakePort([]), b"OK", timeout=3)

    def test_failed_uart_without_full_error_marker_is_not_success(self):
        with self.assertRaises(TimeoutError):
            probe.read_until(FakePort([probe.ERROR[:10]]), b"OK", timeout=0.001)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.elf = bytearray(256)
        self.elf[:7] = b"\x7fELF\x01\x01\x01"
        struct.pack_into("<H", self.elf, 18, 94)
        struct.pack_into("<II", self.elf, 24, 0x400BE000, 52)
        struct.pack_into("<HH", self.elf, 42, 32, 2)
        struct.pack_into("<8I", self.elf, 52, 1, 128, 0x400BE000, 0x400BE000, 4, 4, 5, 4)
        struct.pack_into("<8I", self.elf, 84, 1, 132, 0x3FFB0000, 0x3FFB0000, 4, 4, 6, 4)
        self.elf[128:136] = b"TEXTDATA"
        (self.path / "bridge-text.bin").write_bytes(b"TEXT")
        (self.path / "bridge-data.bin").write_bytes(b"DATA")

    def load(self):
        (self.path / "bridge.elf").write_bytes(self.elf)
        return probe.bridge_artifacts(self.path)

    def test_matching_segments(self):
        entry, segments = self.load()
        self.assertEqual(entry, 0x400BE000)
        self.assertEqual(segments, [(0x400BE000, b"TEXT"), (0x3FFB0000, b"DATA")])

    def test_truncated_elf(self):
        self.elf = self.elf[:10]
        with self.assertRaises(ValueError):
            self.load()

    def test_wrong_architecture(self):
        struct.pack_into("<H", self.elf, 18, 243)
        with self.assertRaises(ValueError):
            self.load()

    def test_flash_entry_rejected(self):
        struct.pack_into("<I", self.elf, 24, 0x400D0000)
        with self.assertRaises(ValueError):
            self.load()

    def test_mismatched_blob(self):
        (self.path / "bridge-text.bin").write_bytes(b"OOPS")
        with self.assertRaises(ValueError):
            self.load()

    def test_segment_overflow(self):
        (self.path / "bridge-text.bin").write_bytes(b"x" * 0x2001)
        with self.assertRaises(ValueError):
            self.load()

    def test_truncated_program_headers(self):
        struct.pack_into("<I", self.elf, 28, 240)
        with self.assertRaises(ValueError):
            self.load()

    def test_wrong_program_header_size(self):
        struct.pack_into("<H", self.elf, 42, 16)
        with self.assertRaises(ValueError):
            self.load()


class MaintenanceSourceContractTests(unittest.TestCase):
    def test_backup_utility_is_read_only(self):
        source = (ROOT / "tools/backup_washer_usb.py").read_text()
        self.assertIn("chip.read_flash(0, FLASH_BYTES", source)
        self.assertIn("chip.flash_md5sum(0, FLASH_BYTES)", source)
        for operation in ("chip.flash_begin(", "chip.flash_block(",
                          "erase_flash(", "write_flash("):
            self.assertNotIn(operation, source)

    def test_application_update_verifies_backup_before_writing(self):
        source = (ROOT / "tools/update_washer_usb_app.py").read_text()
        backup_check = source.index("chip.flash_md5sum(0, len(raw))")
        writing_receipt = source.index("result['phase'] = 'writing'")
        flash_begin = source.index("chip.flash_begin(len(image), 0x10000)")
        self.assertLess(backup_check, writing_receipt)
        self.assertLess(writing_receipt, flash_begin)
        self.assertIn("('preserved-prefix.bin', 0, 0x10000)", source)
        self.assertIn("('preserved-data.bin', 0x1c0000, 0x400000)", source)

    def test_screen_receipt_uses_v4_heartbeat(self):
        source = (ROOT / "tools/update_washer_usb_screen.py").read_text()
        self.assertIn('"v4_heartbeat_verified": False', source)
        self.assertIn('result["v4_heartbeat_verified"] = True', source)
        self.assertNotIn('"v3_heartbeat_verified"', source)


if __name__ == "__main__":
    unittest.main()
