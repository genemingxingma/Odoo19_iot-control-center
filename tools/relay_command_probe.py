"""Explicit, bounded relay command test with direct MQTT delivery observation."""
import json
import os
from pathlib import Path
import threading
import time
import traceback
import uuid

from odoo.addons.iot_control_center.services.mqtt_service import _load_config, mqtt

assert env.cr.dbname == "odoo-26-1-16"
device_id = int(os.environ["IOT_ROLLOUT_DEVICE_ID"])
assert device_id in (39, 59), "only the authorized canary devices"
device = env["iot.device"].browse(device_id).exists()
assert len(device) == 1 and device.active and device.firmware_version == "2.0.2"
identity = device._command_identity()
root = device._mqtt_topic_root()
config = _load_config(env)
events = []
lock = threading.Lock()
subscribed = threading.Event()
pending_subscriptions = set()
started = time.monotonic()
allowed = ("command", "state", "command_id", "last_command_id", "firmware_version", "protocol_version",
           "board_profile", "control_inhibit", "max_on_sec", "delay_active", "uptime_sec", "config_revision",
           "schedule_count", "schedule_version", "expires_at", "command_seq", "reset_reason", "free_stack", "safety_trip")


def emit(label, payload):
    print(label, json.dumps(payload), flush=True)


def connected(client, userdata, flags, rc):
    assert rc == 0
    for serial in set((identity, identity.lower(), identity.upper())):
        for kind in ("command", "status", "telemetry"):
            result, mid = client.subscribe(f"{root}/{serial}/{kind}", qos=1)
            assert result == mqtt.MQTT_ERR_SUCCESS
            pending_subscriptions.add(mid)


def subscription_ack(client, userdata, mid, granted):
    assert all(qos != 128 for qos in granted)
    pending_subscriptions.discard(mid)
    if not pending_subscriptions:
        subscribed.set()


def received(client, userdata, message):
    try:
        raw = json.loads(message.payload)
        if not isinstance(raw, dict):
            return
        item = {"at": time.monotonic(), "kind": message.topic.rsplit("/", 1)[-1],
                "retained": message.retain, "body": raw}
        with lock:
            events.append(item)
            del events[:-256]
        emit("MQTT_EVENT", {"seconds": round(item["at"] - started, 2), "topic": message.topic,
             "retained": message.retain, "bytes": len(message.payload),
             **{key: raw[key] for key in allowed if key in raw}})
    except (TypeError, ValueError):
        emit("INVALID_PAYLOAD", {"bytes": len(message.payload)})


def wait_event(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with lock:
            found = next((item for item in reversed(events) if predicate(item)), None)
        if found:
            return found
        time.sleep(0.1)
    return None


def send(state, max_on_sec, restore_schedule=False):
    env.cr.rollback()
    env.invalidate_all()
    current = env["iot.device"].browse(device_id)
    assert current._command_identity() == identity
    payload = {"state": state, "max_on_sec": max_on_sec, "restore_schedule": restore_schedule}
    if state == "on":
        payload["expires_at"] = int(time.time()) + 30
    sent_at = time.monotonic()
    assert current._publish_command("relay", payload, raise_on_fail=True)
    command_id = current.last_command_id
    env.cr.commit()
    observed = wait_event(lambda item: item["at"] >= sent_at and item["kind"] == "command"
        and item["body"].get("command_id") == command_id, 5)
    confirmed = wait_event(lambda item: item["at"] >= sent_at and not item["retained"]
        and item["kind"] in ("status", "telemetry") and item["body"].get("last_command_id") == command_id
        and item["body"].get("state") == state and item["body"].get("max_on_sec") == max_on_sec, 20)
    emit("COMMAND_RESULT", {"device": device_id, "state": state, "id": command_id,
        "broker_observed": bool(observed), "device_confirmed": bool(confirmed)})
    return bool(observed and confirmed)


def custom_send(command, payload, predicate, repeat_id=None):
    env.cr.rollback()
    env.invalidate_all()
    current = env["iot.device"].browse(device_id)
    command_id = repeat_id or uuid.uuid4().hex
    sent_at = time.monotonic()
    assert current._publish_command(command, dict(payload, command_id=command_id), raise_on_fail=True)
    if command == "relay":
        command_id = current.last_command_id
    env.cr.commit()
    assert wait_event(lambda item: item["at"] >= sent_at and item["kind"] == "command"
        and item["body"].get("command_id") == command_id, 5), "command not observed at broker"
    assert wait_event(lambda item: item["at"] >= sent_at and not item["retained"] and item["kind"] == "status"
        and predicate(item["body"], command_id), 20), "expected device response missing"
    return command_id, sent_at


def extended_tests(snapshot):
    assert send("off", snapshot["max_on_sec"])
    watchdog_id, since = custom_send("relay", {"state": "on", "max_on_sec": 3, "expires_at": int(time.time()) + 30},
        lambda body, command_id: body.get("last_command_id") == command_id and body.get("state") == "on")
    assert wait_event(lambda item: item["at"] > since and not item["retained"]
        and item["body"].get("last_command_id") == watchdog_id and item["body"].get("state") == "off"
        and item["body"].get("safety_trip") is True, 10), "watchdog did not close"
    emit("WATCHDOG_VERIFIED", {"device": device_id, "max_on_sec": 3, "state": "off"})

    timer = {"duration_sec": 8, "max_on_sec": 15, "expires_at": int(time.time()) + 30}
    active = lambda body, command_id: body.get("last_command_id") == command_id and body.get("delay_active") is True
    timer_id, since = custom_send("delay_toggle", timer, active)
    time.sleep(1)
    custom_send("delay_toggle", timer, active, repeat_id=timer_id)
    assert wait_event(lambda item: item["at"] > since and not item["retained"]
        and item["body"].get("last_command_id") == timer_id and item["body"].get("delay_active") is False
        and item["body"].get("state") == "off", 15), "timer did not close"
    emit("TIMER_AND_DUPLICATE_VERIFIED", {"device": device_id, "duration_sec": 8, "state": "off"})

    _, since = custom_send("relay", {"state": "on", "max_on_sec": 5, "expires_at": int(time.time()) - 60},
        lambda body, command_id: body.get("state") == "off" and body.get("last_command_id") != command_id)
    time.sleep(3)
    with lock:
        assert not any(item["at"] >= since and item["kind"] in ("status", "telemetry")
            and item["body"].get("state") == "on" for item in events), "expired ON was executed"
    emit("EXPIRED_ON_REJECTED", {"device": device_id})

    if device_id == 59:
        raw = json.loads(Path("/opt/odoo/iot-v2-isolated-20260906/relay-rollout/device-59-retained-schedule.json").read_bytes())
        assert raw.pop("command") == "schedule_set" and len(raw["entries"]) == snapshot["schedule_count"]
        original_version = raw["version"]
        for version in (original_version + 1, original_version):
            custom_send("schedule_set", dict(raw, version=version), lambda body, command_id:
                body.get("last_command_id") == command_id and body.get("schedule_version") == version
                and body.get("schedule_count") == len(raw["entries"]) and body.get("state") == "off")
        emit("SCHEDULE_APPLY_AND_RESTORE_VERIFIED", {"device": device_id, "entries": len(raw["entries"]), "version": original_version})

    since = time.monotonic()
    first = wait_event(lambda item: item["at"] >= since and item["kind"] == "telemetry", 40)
    assert first and first["body"].get("uptime_sec", 0) > 0
    last = wait_event(lambda item: item["at"] >= first["at"] + 59 and item["kind"] == "telemetry", 100)
    assert last, "continuous telemetry not received"
    with lock:
        samples = [item for item in events if first["at"] <= item["at"] <= last["at"] and item["kind"] in ("status", "telemetry")]
    for item in samples:
        elapsed = item["at"] - first["at"]
        uptime_delta = item["body"].get("uptime_sec", 0) - first["body"]["uptime_sec"]
        assert abs(elapsed - uptime_delta) <= 5, "uptime continuity failed"
        assert item["body"].get("state") == "off" and item["body"].get("schedule_count") == snapshot["schedule_count"]
    emit("STABILITY_VERIFIED", {"device": device_id, "seconds": round(last["at"] - first["at"]),
        "uptime_sec": last["body"]["uptime_sec"], "free_stack": last["body"].get("free_stack")})


client = mqtt.Client(client_id="codex-relay-probe-" + uuid.uuid4().hex, clean_session=True)
if config.get("username"):
    client.username_pw_set(config["username"], config.get("password") or None)
client.on_connect = connected
client.on_subscribe = subscription_ack
client.on_message = received
baseline = None
passed = False
restored = False
try:
    client.connect(config["host"], port=config.get("port") or 1883, keepalive=60)
    client.loop_start()
    assert subscribed.wait(10), "MQTT subscription not acknowledged"
    baseline = wait_event(lambda item: not item["retained"] and item["kind"] in ("status", "telemetry")
        and item["body"].get("state") == "off" and item["body"].get("protocol_version") == 1, 45)
    assert baseline, "fresh OFF report required"
    snapshot = baseline["body"]
    assert snapshot.get("firmware_version") == "2.0.2" and not snapshot.get("delay_active")
    with lock:
        for item in events:
            if item["kind"] == "command" and item["retained"]:
                if item["body"].get("command") == "schedule_clear":
                    # Devices with no schedules legitimately retain this form.
                    assert snapshot.get("schedule_count") == 0
                    assert item["body"].get("version") == snapshot.get("schedule_version")
                else:
                    assert item["body"].get("command") == "schedule_set", "review retained command first"
                    assert len(item["body"].get("entries", [])) == snapshot.get("schedule_count")
    emit("BASELINE", {key: snapshot.get(key) for key in allowed if key in snapshot})
    if send("off", snapshot["max_on_sec"]):
        on_ok = send("on", 30)
        emit("ON_TEST", {"confirmed": on_ok})
        if os.environ.get("IOT_PROBE_EXTENDED") == "1":
            assert on_ok
            extended_tests(snapshot)
        passed = on_ok
    else:
        emit("ON_TEST_SKIPPED", {"reason": "OFF did not receive device confirmation"})
except Exception as error:
    emit("PROBE_STOPPED", {"device": device_id, "error_type": type(error).__name__,
        "line": traceback.extract_tb(error.__traceback__)[-1].lineno})
finally:
    try:
        if baseline:
            snapshot = baseline["body"]
            result = send("off", snapshot["max_on_sec"], restore_schedule=not snapshot.get("control_inhibit", True))
            restored = result
            emit("FINAL_OFF", {"device": device_id, "confirmed": result})
    except Exception as error:
        emit("FINAL_OFF_UNCONFIRMED", {"error_type": type(error).__name__})
    client.loop_stop()
    client.disconnect()
    env.cr.rollback()
emit("PROBE_RESULT", {"device": device_id, "passed": passed and restored})
if not (passed and restored):
    raise SystemExit(1)
