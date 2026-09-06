"""One-device rolling firmware operation through native Odoo ORM.

Execute only in an authorized Odoo shell. Each invocation upgrades at most one
explicit device. No fleet loop, automatic retries or implicit selection exists.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import threading
import time
import traceback
import uuid
from urllib.parse import urlsplit

from odoo import fields
from odoo.addons.iot_control_center.services.mqtt_service import _load_config, mqtt

VERSION = "2.0.2"
ROOT = Path("/opt/odoo/iot-v2-isolated-20260906/relay-rollout")
ACTION = os.environ.get("IOT_ROLLOUT_ACTION", "inspect")
DEVICE_ID = int(os.environ.get("IOT_ROLLOUT_DEVICE_ID", "0"))
assert env.cr.dbname == "odoo-26-1-16", "explicit deployment database required"
live = None


class LiveReports:
    def __init__(self, device):
        self.identity = device._command_identity()
        self.root = device._mqtt_topic_root()
        self.config = _load_config(env)
        self.data = None
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.received = threading.Event()
        self.client = mqtt.Client(client_id="codex-rollout-" + uuid.uuid4().hex, clean_session=True)
        if self.config.get("username"):
            self.client.username_pw_set(self.config["username"], self.config.get("password") or None)
        self.client.on_connect = self.connected
        self.client.on_subscribe = self.subscribed
        self.client.on_message = self.message

    def connected(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe([(f"{self.root}/{self.identity}/status", 1), (f"{self.root}/{self.identity}/telemetry", 1)])

    def subscribed(self, client, userdata, mid, granted):
        if len(granted) == 2 and all(qos != 128 for qos in granted):
            self.ready.set()

    def message(self, client, userdata, message):
        if message.retain:
            return
        try:
            body = json.loads(message.payload)
            if not isinstance(body, dict) or str(body.get("module_id", "")).lower() != self.identity.lower():
                return
            body["_received_at"] = fields.Datetime.now()
            with self.lock:
                self.data = body
            self.received.set()
        except (ValueError, TypeError):
            return

    def start(self):
        self.client.connect(self.config["host"], port=self.config.get("port") or 1883, keepalive=60)
        self.client.loop_start()
        assert self.ready.wait(10), "live MQTT subscription not acknowledged"

    def latest(self):
        with self.lock:
            return dict(self.data) if self.data is not None else None

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()


def emit(label, values):
    print(label, json.dumps(values, ensure_ascii=False), flush=True)


def fresh():
    env.cr.rollback()
    env.invalidate_all()
    device = env["iot.device"].browse(DEVICE_ID).exists()
    assert len(device) == 1 and device.active and device.company_id, "invalid explicit device"
    # V1 sampling reuses existing rows. The largest row ID is not necessarily
    # the most recently received report.
    message = env["iot.mqtt.message"].search([("device_id", "=", device.id)], order="received_at desc, id desc", limit=1)
    payload = json.loads(message.payload) if message else {}
    payload["_received_at"] = message.received_at if message else None
    if live is not None:
        current = live.latest()
        if current is not None:
            payload = current
    return device, payload


def wait_report(predicate, label, seconds=180):
    deadline = time.monotonic() + seconds
    next_notice = 0
    while time.monotonic() < deadline:
        device, report = fresh()
        if predicate(device, report):
            return device, report
        if time.monotonic() >= next_notice:
            emit("WAIT", {"device": DEVICE_ID, "stage": label, "version": device.firmware_version,
                "state": device.relay_state, "last_seen": str(device.last_seen)})
            next_notice = time.monotonic() + 15
        time.sleep(2)
    raise RuntimeError("device acknowledgement timeout: " + label)


def publish(command, payload):
    device, _ = fresh()
    assert device.online, "device offline; no command sent"
    payload = dict(payload, command_id=uuid.uuid4().hex)
    assert device._publish_command(command, payload, raise_on_fail=True)
    command_id = device.last_command_id if command == "relay" else payload["command_id"]
    env.cr.commit()
    assert command_id, "command must have an auditable identity"
    return command_id


def publish_and_confirm(command, payload, predicate):
    command_id = publish(command, payload)
    return wait_report(lambda device, report: report.get("last_command_id") == command_id
                       and predicate(device, report), command, seconds=90)


def restore_state(snapshot):
    age = (fields.Datetime.now() - fields.Datetime.to_datetime(snapshot["captured_at"])).total_seconds()
    assert snapshot["state"] == "off" or 0 <= age < 600, "stale ON snapshot; review current schedules first"
    restored, report = publish_and_confirm("relay", {"state": snapshot["state"],
        "max_on_sec": snapshot["max_on_sec"], "restore_schedule": snapshot["state"] == "off"},
        lambda device, report: device.relay_state == snapshot["state"]
        and report.get("max_on_sec") == snapshot["max_on_sec"] and not report.get("delay_active"))
    assert report.get("protocol_version") == 1 and report.get("schedule_count") == snapshot["schedule_count"]
    emit("STATE_RESTORED", {"device": DEVICE_ID, "serial": restored.serial, "version": restored.firmware_version,
        "before": snapshot["state"], "after": restored.relay_state, "schedules": report.get("schedule_count")})
    return restored, report


def main():
    global live
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ROOT, 0o700)
    if ACTION == "quarantine":
        firmware = env["iot.firmware"].browse(int(os.environ["IOT_ROLLOUT_FIRMWARE_ID"])).exists()
        assert len(firmware) == 1 and firmware.version == VERSION
        assert firmware.checksum == os.environ["IOT_ROLLOUT_SHA256"]
        reason = os.environ.get("IOT_ROLLOUT_QUARANTINE_REASON", "").strip()
        assert 0 < len(reason) <= 1000, "explicit current quarantine reason required"
        firmware.write({"quarantined": True, "quarantine_reason": reason})
        env.cr.commit()
        emit("FIRMWARE_QUARANTINED", {"id": firmware.id, "version": firmware.version})
        return
    if ACTION == "prepare":
        raw = (ROOT / f"firmware-{VERSION}.bin").read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == os.environ["IOT_ROLLOUT_SHA256"], "candidate hash mismatch"
        assert raw[0] == 0xe9 and raw[2] == 3 and raw[3] >> 4 == 2, "wrong flash layout"
        assert len(raw) < 958448 and VERSION.encode() in raw
        company = env["res.company"].browse(int(os.environ["IOT_ROLLOUT_COMPANY_ID"])).exists()
        assert len(company) == 1 and company.country_id, "company/country required"
        firmware = env["iot.firmware"].search([("company_id", "=", company.id),
            ("version", "=", VERSION), ("checksum", "=", digest)], limit=1)
        if not firmware:
            firmware = env["iot.firmware"].create({"name": f"ESP8266 Relay {VERSION} retained schedule fix",
                "version": VERSION, "filename": f"esp8266_relay_v{VERSION}.bin", "file": base64.b64encode(raw),
                "company_id": company.id, "note": "Retained schedule/report stack fix; staged device validation required."})
        assert firmware.image_compatible and not firmware.quarantined
        env.cr.commit()
        emit("FIRMWARE_READY", {"id": firmware.id, "version": VERSION, "sha256": digest, "bytes": len(raw)})
        return

    device, report = fresh()
    emit("DEVICE", {"id": device.id, "serial": device.serial, "version": device.firmware_version,
        "state": device.relay_state, "online": device.online, "board": report.get("board_profile"),
        "protocol": report.get("protocol_version")})
    if ACTION == "inspect":
        allowed = ("firmware_version", "protocol_version", "board_profile", "state", "ota_state",
                   "schedule_count", "schedule_version", "max_on_sec", "delay_active", "control_inhibit",
                   "config_revision", "last_command_id", "command_seq", "mqtt_route", "uptime_sec", "free_heap")
        for message in env["iot.mqtt.message"].search([("device_id", "=", DEVICE_ID)], order="received_at desc, id desc", limit=12):
            raw = json.loads(message.payload)
            emit("RECENT_REPORT", dict({"received_at": str(message.received_at)},
                **{key: raw[key] for key in allowed if key in raw}))
        return
    assert ACTION in ("upgrade", "restore", "restore_state", "network_only"), "unsupported operation"
    assert device.online and (fields.Datetime.now() - device.last_seen).total_seconds() < 120
    assert device.firmware_hardware_profile == "esp8266-1m-dout-64kfs"
    assert report.get("board_profile") in ("IoT-Relay", "IoT-Outlet")
    live = LiveReports(device)
    live.start()
    snapshot_path = ROOT / f"device-{device.id}-to-{VERSION}.json"

    if ACTION == "upgrade":
        assert live.received.wait(40), "fresh live pre-upgrade report required"
        device, report = fresh()
        assert report.get("state") == device.relay_state and report.get("firmware_version") == device.firmware_version
        assert not device.delay_active and not report.get("delay_active"), "active timer; postpone upgrade"
        assert device.relay_state in ("on", "off")
        assert device.firmware_version in ("1.8.10", "2.0.1"), "unreviewed source firmware"
        assert not snapshot_path.exists(), "existing snapshot; inspect before retrying an upgrade"
        snapshot = {"device_id": device.id, "serial": device.serial, "company_id": device.company_id.id,
            "firmware": device.firmware_version, "state": device.relay_state,
            "board": report["board_profile"], "schedule_count": report.get("schedule_count", 0),
            "max_on_sec": report.get("max_on_sec", 0), "captured_at": str(fields.Datetime.now())}
        with snapshot_path.open("x", encoding="utf-8") as stream:
            os.chmod(snapshot_path, 0o600)
            json.dump(snapshot, stream)
            stream.flush()
            os.fsync(stream.fileno())
        firmware = env["iot.firmware"].browse(int(os.environ["IOT_ROLLOUT_FIRMWARE_ID"])).exists()
        assert len(firmware) == 1 and firmware.version == VERSION and firmware.company_id == device.company_id
        wizard = env["iot.firmware.push.wizard"].create({"firmware_id": firmware.id,
            "company_id": device.company_id.id, "device_ids": [(6, 0, [device.id])]})
        assert env["iot.device"].search(wizard._domain_devices()).ids == [device.id], "single-device fence failed"
        requested_at = fields.Datetime.now()
        wizard.action_push()
        env.cr.commit()
        emit("UPGRADE_SENT", {"device": DEVICE_ID, "before": snapshot["state"], "target": VERSION})
        device, report = wait_report(lambda device, report: device.firmware_version == VERSION
            and device.last_seen >= requested_at and report.get("firmware_version") == VERSION,
            "firmware reboot", seconds=180)
        assert report.get("protocol_version") == 1, "V1 controller compatibility was not retained"
        assert report.get("board_profile") == snapshot["board"]
        assert report.get("schedule_count") == snapshot["schedule_count"]
        emit("UPGRADE_VERIFIED", {"device": DEVICE_ID, "version": device.firmware_version,
            "board": report.get("board_profile"), "state": device.relay_state, "protocol": 1})

    snapshot = None if ACTION == "network_only" else json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot:
        assert snapshot["device_id"] == DEVICE_ID and snapshot["serial"].lower() == device.serial.lower()
    assert device.firmware_version in (("2.0.1", VERSION) if ACTION == "network_only" else (VERSION,))
    assert report.get("protocol_version") == 1
    if ACTION == "restore_state":
        restore_state(snapshot)
        return

    # Provision OTA trust from the administrator-owned certificate, checking it
    # against this company's private endpoint before sending any configuration.
    device, report = fresh()
    network = device._network_config_payload()
    endpoint = urlsplit(device.company_id.get_iot_internal_ota_base_url() or "")
    assert endpoint.scheme == "https" and endpoint.hostname, "review company OTA route first"
    certificate = ssl.PEM_cert_to_DER_cert(Path("/etc/iot-ota-proxy/server.crt").read_text())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((endpoint.hostname, endpoint.port or 443), timeout=8) as connection:
        with context.wrap_socket(connection, server_hostname=endpoint.hostname) as secured:
            assert secured.getpeercert(binary_form=True) == certificate, "company OTA certificate mismatch"
    fingerprint = hashlib.sha1(certificate).hexdigest().upper()
    network["ota_tls_fingerprint"] = ":".join(fingerprint[i:i + 2] for i in range(0, 40, 2))
    revision = hashlib.sha256(json.dumps(network, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    network["config_revision"] = revision
    publish_and_confirm("network_set", network, lambda device, report: report.get("config_revision") == revision)
    if ACTION == "network_only":
        emit("NETWORK_VERIFIED", {"device": DEVICE_ID, "version": device.firmware_version})
        return
    restored, report = restore_state(snapshot)
    emit("RESTORE_VERIFIED", {"device": DEVICE_ID, "serial": restored.serial, "version": restored.firmware_version,
        "before": snapshot["state"], "after": restored.relay_state, "schedules": report.get("schedule_count")})
    snapshot["verified_at"] = str(fields.Datetime.now())
    with snapshot_path.open("w", encoding="utf-8") as stream:
        json.dump(snapshot, stream)
        stream.flush()
        os.fsync(stream.fileno())


try:
    main()
except Exception as error:
    env.cr.rollback()
    location = traceback.extract_tb(error.__traceback__)[-1]
    emit("ROLLOUT_STOPPED", {"device": DEVICE_ID, "action": ACTION, "error_type": type(error).__name__,
        "source": Path(location.filename).name, "line": location.lineno})
    # Exception repr may contain a token-bearing URL. Do not print it.
    raise SystemExit(1)
finally:
    if live is not None:
        live.stop()
    env.cr.rollback()
