"""Bounded, read-only MQTT observation using protected Odoo configuration."""
import json
import os
import time
import uuid

from odoo.addons.iot_control_center.services.mqtt_service import _load_config, mqtt

assert env.cr.dbname == "odoo-26-1-16"
device = env["iot.device"].browse(int(os.environ["IOT_ROLLOUT_DEVICE_ID"])).exists()
assert len(device) == 1
identity = device._command_identity()
root = device._mqtt_topic_root()
allowed = ("firmware_version", "protocol_version", "board_profile", "state", "ota_state",
           "schedule_count", "max_on_sec", "delay_active", "control_inhibit", "config_revision",
           "last_command_id", "command_seq", "mqtt_route", "uptime_sec", "free_heap", "module_id",
           "reset_reason", "free_stack")
config = _load_config(env)
client = mqtt.Client(client_id="codex-readonly-" + uuid.uuid4().hex, clean_session=True)
if config.get("username"):
    client.username_pw_set(config["username"], config.get("password") or None)


def connected(client, userdata, flags, rc):
    print("MQTT_OBSERVER", json.dumps({"device": device.id, "identity": identity, "result": rc}), flush=True)
    for serial in set((identity, identity.upper(), identity.lower())):
        for kind in ("status", "telemetry"):
            client.subscribe(f"{root}/{serial}/{kind}", qos=1)


def received(client, userdata, message):
    try:
        raw = json.loads(message.payload)
        print("MQTT_REPORT", json.dumps({"topic": message.topic, "retained": message.retain,
              **{key: raw[key] for key in allowed if key in raw}}), flush=True)
    except (ValueError, TypeError):
        print("MQTT_INVALID_JSON", flush=True)


client.on_connect = connected
client.on_message = received
try:
    client.connect(config["host"], port=config.get("port") or 1883, keepalive=60)
    client.loop_start()
    time.sleep(70)
finally:
    client.loop_stop()
    client.disconnect()
    env.cr.rollback()
