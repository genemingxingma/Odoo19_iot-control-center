"""Inspect, back up/remove, or restore one reviewed retained schedule command."""
import json
import os
from pathlib import Path
import threading
import uuid

from odoo.addons.iot_control_center.services.mqtt_service import _load_config, mqtt, publish_once

assert env.cr.dbname == "odoo-26-1-16"
device_id = int(os.environ["IOT_ROLLOUT_DEVICE_ID"])
assert device_id == 59, "retained-message test is limited to the failed outlet canary"
device = env["iot.device"].browse(device_id).exists()
assert len(device) == 1 and device._command_identity() == "0676B5"
topic = f"{device._mqtt_topic_root()}/{device._command_identity()}/command"
config = _load_config(env)
action = os.environ.get("IOT_RETAINED_ACTION", "inspect")
assert action in ("inspect", "remove", "restore")
backup = Path("/opt/odoo/iot-v2-isolated-20260906/relay-rollout/device-59-retained-schedule.json")
event = threading.Event()
retained = []
client = mqtt.Client(client_id="codex-retained-probe-" + uuid.uuid4().hex, clean_session=True)
if config.get("username"):
    client.username_pw_set(config["username"], config.get("password") or None)


def connected(client, userdata, flags, rc):
    assert rc == 0
    client.subscribe(topic, qos=1)


def received(client, userdata, message):
    if message.topic == topic and message.retain:
        retained.append(bytes(message.payload))
        event.set()


client.on_connect = connected
client.on_message = received
try:
    if action == "restore":
        assert device.firmware_version == "2.0.2", "only restore onto the fixed canary"
        data = backup.read_bytes()
    else:
        client.connect(config["host"], port=config.get("port") or 1883, keepalive=60)
        client.loop_start()
        assert event.wait(10) and len(retained) == 1
        data = retained[0]
    raw = json.loads(data)
    assert raw.get("command") == "schedule_set"
    assert set(raw) <= {"command", "version", "entries", "max_on_sec", "command_id"}
    assert isinstance(raw.get("entries"), list) and len(raw["entries"]) == 14
    if action == "remove":
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        assert publish_once(env, topic, "", retain=True)
    elif action == "restore":
        assert publish_once(env, topic, data, retain=True)
    print("RETAINED_SCHEDULE_" + action.upper(), json.dumps({"device": device_id, "entries": len(raw["entries"]),
        "version": raw.get("version"), "backup_saved": backup.exists()}), flush=True)
finally:
    client.loop_stop()
    client.disconnect()
    env.cr.rollback()
