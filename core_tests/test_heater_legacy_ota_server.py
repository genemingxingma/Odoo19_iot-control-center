import hashlib
import http.client
import importlib.util
import json
from email.message import Message
from pathlib import Path
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("heater_legacy_ota_server", ROOT / "tools/heater_legacy_ota_server.py")
ota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota)


class LegacyOtaTests(unittest.TestCase):
    def setUp(self):
        self.private = tempfile.TemporaryDirectory()
        self.directory = Path(self.private.name)
        self.session = ota.Session(self.directory, "127.0.0.1/32")
        self.headers = Message()
        for key, value in {
            "Host": ota.HOST, "x-ESP8266-mode": "sketch",
            "x-ESP8266-STA-MAC": "02:00:00:12:34:56",
            "x-ESP8266-Chip-ID": str(int("123456", 16)),
            "x-ESP8266-chip-size": "4194304", "x-ESP8266-free-space": "900000",
            "x-ESP8266-sketch-size": "400000", "x-ESP8266-sketch-md5": "1" * 32,
        }.items():
            self.headers[key] = value
        self.path = ota.TARGET + "?uuid=123456"
        self.device = ota.inspect_request(self.path, self.headers)

    def tearDown(self):
        self.private.cleanup()

    def release(self, image_bytes=None, **override):
        image = image_bytes
        if image is None:
            image = b"\xe9" + b"synthetic-not-executable\0" + b"IMYHEATERMIG1:123456:4M1M:END" + b"\0" * 32
        candidate = self.directory / "migration.bin"
        candidate.write_bytes(image)
        manifest = {
            "schema": 1, "heater_load_isolated": True, "configuration_migration_reviewed": True,
            "expires_at": int(time.time()) + 900, "chip_id": self.device["chip_id"],
            "mac": self.device["mac"], "source_sketch_md5": self.device["sketch_md5"],
            "image": str(candidate), "image_sha256": hashlib.sha256(image).hexdigest(),
        }
        manifest.update(override)
        (self.directory / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
        return image

    def http_get(self, path=None, headers=None):
        server = ota.Server(("127.0.0.1", 0), self.session)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            connection.request("GET", path or self.path, headers=headers or dict(self.headers.items()))
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_default_is_observation_only(self):
        status, headers, body = self.http_get()
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(headers["Content-Length"], "0")
        receipt = json.loads((self.directory / "observations.json").read_text())
        self.assertEqual(receipt["completed_downloads"], 0)
        self.assertEqual(receipt["devices"][0]["chip_id"], "123456")

    def test_legacy_binary_response_has_exact_length_and_md5(self):
        image = self.release()
        status, headers, body = self.http_get()
        self.assertEqual(status, 200)
        self.assertEqual(body, image)
        self.assertEqual(int(headers["Content-Length"]), len(image))
        self.assertEqual(headers["x-MD5"], hashlib.md5(image).hexdigest())
        self.assertEqual(self.session.transfers, 1)

    def test_unisolated_load_blocks_release(self):
        self.release(heater_load_isolated=False)
        self.assertEqual(self.http_get()[0], 204)

    def test_expired_or_long_lived_authorization_blocks_release(self):
        for expires in (int(time.time()) - 1, int(time.time()) + 7200):
            with self.subTest(expires=expires):
                self.release(expires_at=expires)
                self.assertIsNone(self.session.image_for(self.device))

    def test_other_device_or_old_application_is_not_upgraded(self):
        for override in ({"chip_id": "FFFFFF"}, {"mac": "02:00:00:00:00:01"},
                         {"source_sketch_md5": "2" * 32}):
            with self.subTest(override=override):
                self.release(**override)
                self.assertIsNone(self.session.image_for(self.device))

    def test_generic_new_application_without_migration_marker_is_blocked(self):
        self.release(b"\xe9" + b"IMYTESTFW1:heater:heater-esp12s-ds18b20-v1:32008:END" + b"\0" * 64)
        self.assertIsNone(self.session.image_for(self.device))

    def test_corrupt_or_too_large_image_is_blocked(self):
        self.release(image_sha256="0" * 64)
        self.assertIsNone(self.session.image_for(self.device))
        self.release()
        for change in ({"free_bytes": 16}, {"flash_bytes": 1048576}):
            self.assertIsNone(self.session.image_for({**self.device, **change}))

    def test_image_cannot_escape_protected_session(self):
        self.release(image=str(ROOT / "firmware/instruments/.pio/build/heater/firmware.bin"))
        self.assertIsNone(self.session.image_for(self.device))

    def test_malformed_release_fails_closed(self):
        (self.directory / "release.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.http_get()[0], 204)

    def test_duplicate_query_wrong_host_or_mismatched_chip_is_rejected(self):
        self.assertEqual(self.http_get(path=self.path + "&uuid=654321")[0], 404)
        headers = dict(self.headers.items())
        for override in ({"Host": "example.invalid"}, {"x-ESP8266-Chip-ID": "7"},
                         {"x-ESP8266-mode": "spiffs"}):
            self.assertEqual(self.http_get(headers={**headers, **override})[0], 404)

    def test_unrelated_paths_never_expose_files(self):
        for path in ("/release.json", "/../migration.bin", "/network.json", "/"):
            self.assertEqual(self.http_get(path=path)[0], 404)

    def test_unapproved_network_is_blocked(self):
        import ipaddress
        self.session.allowed_network = ipaddress.ip_network("192.0.2.0/24")
        self.assertEqual(self.http_get()[0], 403)

    def test_repository_cannot_hold_private_session(self):
        with self.assertRaises(ValueError):
            ota.Session(ROOT, "127.0.0.1/32")


if __name__ == "__main__":
    unittest.main()
