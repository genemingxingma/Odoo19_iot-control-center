import json
import unittest
from datetime import datetime, timezone
from core.telemetry import decode_binary, decode_json, envelope, measurement

class TelemetryContractTest(unittest.TestCase):
    def frame(self):
        body = bytes([250, 206, 0, 0x68, 0xc7, 32, 1, 2, 0, 250, 0, 55])
        return body + bytes([sum(body) & 255])

    def test_binary_decoding(self):
        value = decode_binary(self.frame())[0]
        self.assertEqual((value.node, value.channel, value.temperature, value.humidity), ("68C7", "CH01", 25, 55))

    def test_corrupt_and_truncated_frames_raise(self):
        for frame in [b"", self.frame()[:-1], self.frame()[:-1] + b"\x00", b"xx" + self.frame()[2:]]:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode_binary(frame)

    def test_non_finite_and_out_of_range_samples_raise(self):
        for t, h in [(float("nan"), 50), (1, float("inf")), (200, 50), (20, 101), (0, 0), (True, 55)]:
            with self.subTest(t=t, h=h), self.assertRaises(ValueError):
                measurement("a", "b", t, h)

    def test_event_replay_keeps_identity_time_and_digest(self):
        data = {"protocol_version": 2, "event_id": "a" * 64, "received_at_ms": 1788602400000}
        first = envelope(data, now=datetime(2026, 9, 6))
        second = envelope(data, now=datetime(2026, 9, 7))
        self.assertEqual(first, second)

    def test_json_timestamp_normalized_to_utc(self):
        data = {"gateway_serial": "registered", "reported_at": "2026-09-06T12:00:00+07:00",
                "probes": [{"probe_code": "CH01", "temperature": 20, "humidity": 50}]}
        _, at, _ = decode_json(json.dumps(data), datetime(2026, 9, 6, 5))
        self.assertEqual(at, datetime(2026, 9, 6, 5))

    def test_duplicate_channels_rejected(self):
        probe = {"probe_code": "CH01", "temperature": 20, "humidity": 50}
        with self.assertRaises(ValueError):
            decode_json(json.dumps({"gateway_serial": "g", "probes": [probe, probe]}), datetime(2026, 9, 6))

    def test_unversioned_and_future_envelope_rejected(self):
        for value in [{}, {"protocol_version": 2, "event_id": "a" * 64, "received_at_ms": 9999999999999}]:
            with self.assertRaises(ValueError):
                envelope(value, now=datetime(2026, 9, 6))

if __name__ == "__main__":
    unittest.main()
