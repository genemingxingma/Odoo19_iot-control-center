import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import update_washer_usb_screen as update


class Port:
    def __init__(self, replies):
        self.replies = list(replies)
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def read(self, count):
        return self.replies.pop(0) if self.replies else b""


class UploadTests(unittest.TestCase):
    def test_blocks_and_tail_each_acknowledged(self):
        port = Port([b"\x05"] * 4)
        progress = []
        raw = b"x" * 9000
        update.transfer(port, raw, progress.append)
        self.assertEqual(progress, [0, 4096, 8192, 9000])
        self.assertEqual([len(x) for x in port.writes[1:]], [4096, 4096, 808])
        self.assertEqual(b"".join(port.writes[1:]), raw)
        self.assertEqual(port.writes[0], b"whmi-wri 9000,115200,0\xff\xff\xff")

    def test_bad_initial_ack_sends_no_binary(self):
        port = Port([b"\x00"])
        with self.assertRaises(RuntimeError):
            update.transfer(port, b"x" * 9000, lambda count: None)
        self.assertEqual(len(port.writes), 1)

    def test_bad_block_ack_never_retries_or_continues(self):
        port = Port([b"\x05", b"\x1a"])
        progress = []
        with self.assertRaises(RuntimeError):
            update.transfer(port, b"x" * 9000, progress.append)
        self.assertEqual(len(port.writes), 2)
        self.assertEqual(progress, [0])

    def test_timeout_is_not_success(self):
        with patch.object(update.time, "monotonic", side_effect=[0, 0, 20]):
            with self.assertRaises(TimeoutError):
                update.wait_ack(Port([]), 15)

    def test_partial_host_write(self):
        class Partial(Port):
            def write(self, data):
                self.writes.append(data[:3])
                return min(3, len(data))
        port = Partial([])
        update.write_all(port, b"0123456789")
        self.assertEqual(b"".join(port.writes), b"0123456789")

    def test_no_progress_aborts(self):
        port = Port([])
        with patch.object(port, "write", return_value=0):
            with self.assertRaises(IOError):
                update.write_all(port, b"binary")

    def test_correct_model_and_capacity(self):
        reply = b"comok 1,101,TJC8048X550_011C,52,123,TESTONLY,33554432\xff\xff\xff"
        self.assertEqual(update.screen_identity(reply), 33554432)

    def test_wrong_touch_variant_rejected(self):
        with self.assertRaises(ValueError):
            update.screen_identity(b"comok 1,101,TJC8048X550_011R,52,123,TESTONLY,33554432\xff\xff\xff")

    def test_observed_x5_capacity_extension(self):
        self.assertEqual(update.screen_identity(b"comok 1,101,TJC8048X550_011C,52,123,TESTONLY,128974848-0\xff\xff\xff"),128974848)
        for field in (b"128974848-1", b"128974848-0garbage", b"33554432-0", b"-1", b"0", b"999999999"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                update.screen_identity(b"comok 1,101,TJC8048X550_011C,52,123,TESTONLY,"+field+b"\xff\xff\xff")

    def test_truncated_identity_rejected(self):
        with self.assertRaises(ValueError):
            update.screen_identity(b"TJC8048X550_011C")

    def test_sha256_checked_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.tft"
            raw = b"x" * 8192
            path.write_bytes(raw)
            self.assertEqual(update.verified_tft(path, hashlib.sha256(raw).hexdigest()), raw)
            with self.assertRaises(ValueError):
                update.verified_tft(path, "0" * 64)
            with self.assertRaises(ValueError):
                update.verified_tft(path, "missing")


if __name__ == "__main__":
    unittest.main()
