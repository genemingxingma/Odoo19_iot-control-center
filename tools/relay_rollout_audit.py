"""Read-only fleet reconciliation plus bounded, fresh MQTT stability evidence."""
import hashlib
import json
import os
from pathlib import Path
import ssl
import threading
import time
import uuid

from odoo import fields
from odoo.addons.iot_control_center.services.mqtt_service import _load_config, mqtt

assert env.cr.dbname == "odoo-26-1-16"
root = Path("/opt/odoo/iot-v2-isolated-20260906/relay-rollout")
expected_ids = (11, 39, 55, 56, 57, 58, 59, 60, 61, 62, 63)
unexpected = set(env["iot.device"].search([("active", "=", True)]).ids) - set(expected_ids) - {37, 38}
assert not unexpected, "active fleet inventory changed; review additional devices"
certificate = ssl.PEM_cert_to_DER_cert(Path("/etc/iot-ota-proxy/server.crt").read_text())
digest = hashlib.sha1(certificate).hexdigest().upper()
fingerprint = ":".join(digest[index:index + 2] for index in range(0, 40, 2))
expected = {}
rows = []
for device in env["iot.device"].browse(expected_ids).exists():
    snapshot = json.loads((root / f"device-{device.id}-to-2.0.2.json").read_text())
    assert snapshot.get("verified_at") and device.company_id.id == snapshot["company_id"]
    assert device.active
    assert device.firmware_version == "2.0.2" and device.relay_state == snapshot["state"]
    assert device.online and (fields.Datetime.now() - device.last_seen).total_seconds() < 120
    assert device.firmware_hardware_profile == "esp8266-1m-dout-64kfs"
    network = device._network_config_payload()
    network["ota_tls_fingerprint"] = fingerprint
    revision = hashlib.sha256(json.dumps(network, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    serial = device._command_identity()
    expected[serial] = {"snapshot": snapshot, "revision": revision, "host": network["mqtt_primary_host"]}
    rows.append({"id": device.id, "serial": serial, "version": device.firmware_version,
        "before": snapshot["state"], "after": device.relay_state, "board": snapshot["board"], "country": device.company_id.country_id.code,
        "schedules": snapshot["schedule_count"], "max_on_sec": snapshot["max_on_sec"]})
assert len(rows) == len(expected_ids)
topic_root = env["iot.device"].browse(expected_ids[0])._mqtt_topic_root()
config = _load_config(env)
samples = {serial: [] for serial in expected}
lock = threading.Lock()
ready = threading.Event()


def connected(client, userdata, flags, rc):
    assert rc == 0
    client.subscribe(f"{topic_root}/+/telemetry", qos=1)


def subscription_ack(client, userdata, mid, granted):
    assert all(qos != 128 for qos in granted)
    ready.set()


def received(client, userdata, message):
    serial = message.topic.rsplit("/", 2)[-2]
    if message.retain or serial not in expected:
        return
    try:
        raw = json.loads(message.payload)
        if isinstance(raw, dict):
            with lock:
                samples[serial].append((time.monotonic(), raw))
    except (ValueError, TypeError):
        pass


client = mqtt.Client(client_id="codex-fleet-audit-" + uuid.uuid4().hex, clean_session=True)
if config.get("username"):
    client.username_pw_set(config["username"], config.get("password") or None)
client.on_connect = connected
client.on_subscribe = subscription_ack
client.on_message = received
try:
    client.connect(config["host"], port=config.get("port") or 1883, keepalive=60)
    client.loop_start()
    assert ready.wait(10)
    print("FLEET_OBSERVATION_STARTED", json.dumps({"devices": len(rows), "seconds": 75}), flush=True)
    time.sleep(75)
finally:
    client.loop_stop()
    client.disconnect()

for row in rows:
    serial = row["serial"]
    reports = samples[serial]
    assert len(reports) >= 2, "insufficient fresh telemetry: " + serial
    first_time, first = reports[0]
    for received_at, raw in reports:
        snapshot = expected[serial]["snapshot"]
        assert raw.get("firmware_version") == "2.0.2" and raw.get("protocol_version") == 1
        assert str(raw.get("module_id", "")).lower() == serial.lower()
        assert raw.get("state") == snapshot["state"] and raw.get("board_profile") == snapshot["board"]
        assert raw.get("schedule_count") == snapshot["schedule_count"] and raw.get("max_on_sec") == snapshot["max_on_sec"]
        assert not raw.get("delay_active") and not raw.get("safety_trip")
        assert raw.get("control_inhibit") is False, "scheduled control still inhibited: " + serial
        assert raw.get("config_revision") == expected[serial]["revision"]
        assert raw.get("mqtt_route") == "primary" and raw.get("mqtt_host") == expected[serial]["host"]
        assert abs((raw["uptime_sec"] - first["uptime_sec"]) - (received_at - first_time)) < 5, "uptime discontinuity: " + serial
    row.update({"fresh_samples": len(reports), "uptime_sec": reports[-1][1]["uptime_sec"],
        "free_stack": reports[-1][1].get("free_stack"), "company_primary_route": True,
        "scheduled_control_enabled": True})
    print("FLEET_DEVICE_VERIFIED", json.dumps(row), flush=True)

env.cr.rollback()
env.invalidate_all()
pending = env["iot.device"].browse((37, 38)).read(["serial", "online", "firmware_version", "last_seen"])
module = env["ir.module.module"].search([("name", "=", "iot_control_center")], limit=1)
firmware = env["iot.firmware"].browse(16)
assert firmware.version == "2.0.2" and firmware.image_compatible and not firmware.quarantined
assert firmware.checksum == "1af36e7bc1e5a56c79a62e901f000b1c1cf72dbebfee0339911619e92f86b651"
assert env["iot.firmware"].browse(15).quarantined
result = {"verified_at": str(fields.Datetime.now()), "version": "2.0.2", "devices": rows,
    "pending": pending, "production_module": module.latest_version, "old_2_0_1_quarantined": True}
path = root / "fleet-2.0.2-final.json"
with path.open("w", encoding="utf-8") as stream:
    os.chmod(path, 0o600)
    json.dump(result, stream, default=str)
    stream.flush()
    os.fsync(stream.fileno())
print("FLEET_AUDIT_OK", json.dumps({"verified": len(rows), "pending": pending,
    "production_module": module.latest_version}, default=str), flush=True)
env.cr.rollback()
