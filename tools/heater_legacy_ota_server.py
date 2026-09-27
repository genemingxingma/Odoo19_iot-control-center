"""Bounded, LAN-only compatibility endpoint for first-generation heater OTA.

Without an externally reviewed migration release this always returns HTTP 204.
Never serve an ordinary application image as a first-migration image.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TARGET = "/hj_aiot/heating/target"
HOST = "iot.huanjibio.com"
FLASH_SIZE = 4 * 1024 * 1024
MAX_IMAGE_SIZE = 1000000
MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")


def private_directory(value):
    path = Path(value).resolve()
    if not path.is_dir() or path.is_relative_to(ROOT):
        raise ValueError("Use an existing protected directory outside the repository")
    return path


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def inspect_request(path, headers):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != TARGET:
        raise ValueError("Unknown endpoint")
    query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=2)
    if set(query) != {"uuid"} or len(query["uuid"]) != 1:
        raise ValueError("Invalid device query")
    uid = query["uuid"][0]
    if not re.fullmatch(r"[0-9a-fA-F]{1,6}", uid) or int(uid, 16) == 0:
        raise ValueError("Invalid chip identity")
    host = headers.get("Host", "").lower()
    if host not in (HOST, HOST + ":80"):
        raise ValueError("Unexpected virtual host")
    if headers.get("x-ESP8266-mode") != "sketch":
        raise ValueError("Only application updates are supported")
    mac = headers.get("x-ESP8266-STA-MAC", "").lower()
    if not MAC.fullmatch(mac):
        raise ValueError("Missing controller identity")
    chip_header = headers.get("x-ESP8266-Chip-ID")
    if chip_header is not None and (not re.fullmatch(r"[0-9]{1,8}", chip_header)
                                    or int(chip_header) != int(uid, 16)):
        raise ValueError("Inconsistent controller identity")
    geometry = {}
    for key, header in (("flash_bytes", "chip-size"), ("free_bytes", "free-space"),
                        ("sketch_bytes", "sketch-size")):
        value = headers.get("x-ESP8266-" + header, "")
        if not re.fullmatch(r"[0-9]{1,9}", value):
            raise ValueError("Missing flash geometry")
        geometry[key] = int(value)
    if not 0 < geometry["sketch_bytes"] <= geometry["flash_bytes"]:
        raise ValueError("Invalid application geometry")
    if not 0 <= geometry["free_bytes"] <= geometry["flash_bytes"]:
        raise ValueError("Invalid free space")
    old_md5 = headers.get("x-ESP8266-sketch-md5", "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", old_md5):
        raise ValueError("Missing application digest")
    return {"chip_id": uid.upper().zfill(6), "mac": mac, "sketch_md5": old_md5, **geometry}


class Session:
    def __init__(self, directory, allowed_network):
        self.directory = private_directory(directory)
        self.allowed_network = ipaddress.ip_network(allowed_network)
        self.lock = threading.Lock()
        self.observed = {}
        self.transfers = 0
        self.last_result = "waiting_for_legacy_device"
        self.release_error = False
        self.save()

    def save(self):
        atomic_json(self.directory / "observations.json", {
            "schema": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "observe_unless_external_release_authorized",
            "last_result": self.last_result, "completed_downloads": self.transfers,
            "download_is_not_installation_acceptance": True,
            "devices": list(self.observed.values()),
        })

    def observe(self, device):
        with self.lock:
            identity = device["mac"]
            if identity not in self.observed and len(self.observed) >= 32:
                raise ValueError("Observation capacity reached")
            previous = self.observed.get(identity, {})
            device["requests"] = previous.get("requests", 0) + 1
            device["seen_at"] = datetime.now(timezone.utc).isoformat()
            self.observed[identity] = device
            self.last_result = "legacy_request_received_no_image_by_default"
            self.save()

    def image_for(self, device):
        with self.lock:
            release = self.directory / "release.json"
            if not release.exists():
                return None
            try:
                if release.stat().st_size > 8192:
                    raise ValueError("Oversized release")
                m = json.loads(release.read_text(encoding="utf-8"))
                if (m.get("schema") != 1 or m.get("heater_load_isolated") is not True
                        or m.get("configuration_migration_reviewed") is not True
                        or not isinstance(m.get("expires_at"), int)
                        or not time.time() < m["expires_at"] <= time.time() + 3600):
                    raise ValueError("Release is not authorized for this maintenance hour")
                if (m.get("chip_id") != device["chip_id"] or m.get("mac") != device["mac"]
                        or device["flash_bytes"] != FLASH_SIZE
                        or m.get("source_sketch_md5") != device["sketch_md5"]):
                    return None
                image_path = Path(m["image"]).resolve()
                if not image_path.is_relative_to(self.directory):
                    raise ValueError("Image must be in the protected session directory")
                if not 32 <= image_path.stat().st_size <= MAX_IMAGE_SIZE:
                    raise ValueError("Invalid application size")
                image = image_path.read_bytes()
                marker = f'IMYHEATERMIG1:{device["chip_id"]}:4M1M:END'.encode()
                if (image[0] != 0xE9 or marker not in image
                        or len(image) > device["free_bytes"]
                        or hashlib.sha256(image).hexdigest() != m.get("image_sha256")):
                    raise ValueError("Wrong image, geometry or reviewed digest")
                return image
            except (ValueError, KeyError, TypeError, OSError):
                self.release_error = True
                self.last_result = "release_rejected_no_image_sent"
                self.save()
                return None

    def downloaded(self):
        with self.lock:
            self.transfers += 1
            self.last_result = "download_completed_installation_not_verified"
            self.save()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Heater-Maintenance"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, *_):
        # HTTP requests can contain real controller IDs; no raw access logs.
        pass

    def reply(self, status, payload=b"", content_type="text/plain; charset=utf-8", md5=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if md5:
            self.send_header("x-MD5", md5)
        self.end_headers()
        self.close_connection = True
        if payload:
            self.wfile.write(payload)

    def do_GET(self):
        session = self.server.session
        try:
            if ipaddress.ip_address(self.client_address[0]) not in session.allowed_network:
                self.reply(403)
                return
            if self.path == "/healthz":
                self.reply(200, b"ok; legacy OTA observer; no image served without reviewed release\n")
                return
            if len(self.path) > 256 or self.headers.get("Transfer-Encoding"):
                self.reply(400)
                return
            if self.headers.get("Content-Length", "0") != "0":
                self.reply(400)
                return
            device = inspect_request(self.path, self.headers)
            session.observe(device)
            image = session.image_for(device)
            if image is None:
                self.reply(204)
                return
            # ESPhttpUpdate checks Content-Length and x-MD5 before rebooting.
            self.reply(200, image, "application/octet-stream", hashlib.md5(image).hexdigest())
            session.downloaded()
        except (ValueError, KeyError):
            self.reply(404)
        except (OSError, socket.timeout):
            # A disconnected client has not completed a download.
            pass

    def do_POST(self):
        self.reply(405)

    do_PUT = do_DELETE = do_POST


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, session):
        self.session = session
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--allow-network", required=True)
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--hours", type=float, default=12)
    args = parser.parse_args()
    bind = ipaddress.ip_address(args.bind)
    subnet = ipaddress.ip_network(args.allow_network)
    if bind.version != 4 or bind not in subnet or not bind.is_private or bind.is_unspecified:
        parser.error("Bind to one private LAN IPv4 address within the allowed network")
    if subnet.prefixlen < 24 or not 0 < args.hours <= 24:
        parser.error("Use a /24 or narrower subnet and a session no longer than 24 hours")
    session = Session(args.private_dir, args.allow_network)
    server = Server((args.bind, 80), session)
    server.timeout = 1
    deadline = time.monotonic() + args.hours * 3600
    print("LEGACY_OTA_OBSERVER_READY; firmware delivery disabled by default", flush=True)
    try:
        while time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
