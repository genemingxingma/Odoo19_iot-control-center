"""Versioned instrument contracts, independent of Odoo and device transport."""
import hashlib
import json
import math
import re

PROTOCOL = 1
MAX_BODY = 32768
MAX_STEPS = 32
KINDS = {"heater", "washer"}
HEATER_HARDWARE = "heater-esp12s-ds18b20-v1"
STEP_KINDS = {"home", "fill_a", "fill_b", "wash", "drain", "dry", "wait"}
HEATER_FAULTS = {"none", "sensor", "no_rise", "over_temperature", "storage", "loop_stalled", "configuration"}


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("number required")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("number outside permitted range")
    return value


def integer(value, low, high):
    number(value, low, high)
    if int(value) != value:
        raise ValueError("integer required")
    return int(value)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("invalid identity")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def washer_speed_default(kind):
    """Source defaults in rev/s, not motor voltage; do not rewrite released recipes."""
    return {"wash": 1.0, "dry": 10.0}.get(kind, 0.0)


def recipe(value):
    if not isinstance(value, dict) or value.get("schema") != PROTOCOL:
        raise ValueError("unsupported recipe schema")
    identifier(value.get("id"))
    label = value.get("label", value["id"][:48])
    if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9 _./()-]{1,48}", label):
        raise ValueError("screen label must be 1..48 basic Latin characters")
    integer(value.get("revision"), 1, 2147483647)
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("recipe requires 1..32 configured steps")
    if any(not isinstance(s, dict) for s in steps):
        raise ValueError("step object required")
    # Homing is a safety preamble owned by the device contract, not a step the
    # operator must remember to add to every platform program.
    if steps[0].get("kind") != "home":
        if len(steps) == MAX_STEPS:
            raise ValueError("automatic homing leaves room for at most 31 configured steps")
        steps = [dict(kind="home", duration_s=10, rps=0, reverse_s=5, cycles=0), *steps]
    liquid, total, clean = False, 0, []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("kind") not in STEP_KINDS:
            raise ValueError("unsupported step")
        kind = step["kind"]
        duration = integer(step.get("duration_s"), 1, 3600 if kind in {"wash", "wait"} else 300)
        speed = number(step.get("rps", 0), 0, 10)
        reverse = integer(step.get("reverse_s", 5), 1, 60)
        cycles = integer(step.get("cycles", 0), 0, 1800)
        if cycles:
            if kind != "wash":
                raise ValueError("cycle counts only apply to washing")
            duration = integer(cycles * 2 * reverse, 1, 3600)
        if kind in {"wash", "dry"} and speed <= 0:
            raise ValueError("motion speed must be positive")
        if kind not in {"wash", "dry"} and speed != 0:
            raise ValueError("speed only applies to wash/dry")
        if kind.startswith("fill"):
            if liquid:
                raise ValueError("drain before refilling")
            liquid = True
        elif kind == "wash" and not liquid:
            raise ValueError("wash requires a preceding fill")
        elif kind == "drain":
            liquid = False
        elif kind == "dry" and liquid:
            raise ValueError("drain before drying")
        if kind != "wait":
            total += duration
        item = dict(kind=kind, duration_s=duration, rps=speed, reverse_s=reverse)
        if cycles:
            item["cycles"] = cycles
        clean.append(item)
    if liquid or total > 14400:
        raise ValueError("recipe must finish drained and within four hours")
    return dict(schema=PROTOCOL, id=value["id"], label=label, revision=value["revision"], steps=clean)


def program_catalog(device_uid, programs):
    """A complete authoritative snapshot; failures must never look like an empty list."""
    identifier(device_uid)
    clean = [recipe(p) for p in programs]
    if len({p["id"] for p in clean}) != len(clean):
        raise ValueError("duplicate program identities")
    clean.sort(key=lambda p: p["id"])
    body = canonical(dict(schema=1, complete=True, device_uid=device_uid, count=len(clean), programs=clean))
    if len(body.encode("utf-8")) > 24576:
        raise ValueError("program catalog exceeds device storage transaction budget")
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


def targets(payload):
    if "b" in payload:
        raise ValueError("single-channel heater required")
    result = {"a": number(payload.get("a"), 10, 50)}
    if any(round(v * 4) != v * 4 for v in result.values()):
        raise ValueError("setpoints use 0.25 degree increments")
    return result


def command(kind, name, payload):
    if kind not in KINDS or not isinstance(payload, dict):
        raise ValueError("invalid command")
    if name == "stop":
        return {}
    if kind == "heater" and name == "set_temperature":
        result = targets(payload)
        result["rise_window_s"] = integer(payload.get("rise_window_s"), 30, 3600)
        result["minimum_rise_c"] = number(payload.get("minimum_rise_c"), 0.125, 5)
        return result
    if kind == "washer" and name == "load_recipe":
        return recipe(payload)
    if name == "ota":
        # The signed package is served by this same authenticated origin.
        identifier(payload.get("release"))
        return {"release": payload["release"]}
    raise ValueError("unsupported command for this instrument")


def event(value, kind):
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
        raise ValueError("unsupported event protocol")
    for key in ("event_id", "boot_id"):
        identifier(value.get(key))
    integer(value.get("seq"), 1, 2147483647)
    integer(value.get("uptime_ms"), 0, 4294967295)
    integer(value.get("sampled_at"), 0, 4102444800)
    status = value.get("status")
    if "observation" in value and type(value["observation"]) is not bool:
        raise ValueError("boolean observation flag required")
    if not isinstance(status, dict):
        raise ValueError("status required")
    if status.get("state") not in {"idle", "heating", "running", "waiting", "fault", "updating", "uncommissioned"}:
        raise ValueError("invalid state")
    if not isinstance(status.get("firmware"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", status["firmware"]):
        raise ValueError("invalid firmware version")
    if kind == "heater":
        if status.get("hardware") != HEATER_HARDWARE or "b" in status:
            raise ValueError("unsupported heater hardware or channel layout")
        if status.get("control_interface") != "heater-control-v1":
            raise ValueError("unsupported heater control interface")
        if status.get("local_enable") is not True or status.get("remote_start") is not False:
            raise ValueError("unsafe heater start policy")
        if "alarm" in value and type(value["alarm"]) is not bool:
            raise ValueError("boolean alarm flag required")
        if "settings_ready" in status and type(status["settings_ready"]) is not bool:
            raise ValueError("boolean settings status required")
        for channel in ("a",):
            probe = status.get(channel)
            if not isinstance(probe, dict) or type(probe.get("valid")) is not bool:
                raise ValueError("probe quality required")
            if probe["valid"]:
                number(probe.get("temperature"), -20, 85)
            if type(probe.get("output")) is not bool:
                raise ValueError("boolean required")
            if probe.get("fault", "none") not in HEATER_FAULTS:
                raise ValueError("invalid heater fault")
            number(probe.get("target"), 10, 50)
        if "enabled" in status and type(status["enabled"]) is not bool:
            raise ValueError("boolean heating permission required")
        if "dropped_observations" in status:
            integer(status["dropped_observations"], 0, 2147483647)
        if "chip_id" in status and not re.fullmatch(r"[0-9A-Fa-f]{6}", str(status["chip_id"])):
            raise ValueError("invalid chip identity")
        if "ip" in status:
            import ipaddress
            if not isinstance(status["ip"], str):
                raise ValueError("invalid IP address")
            if status["ip"]:
                ipaddress.IPv4Address(status["ip"])
        if status.get("settings_ready"):
            integer(status.get("rise_window_s"), 30, 3600)
            number(status.get("minimum_rise_c"), 0.125, 5)
    else:
        if "temperature_valid" in status:
            if type(status["temperature_valid"]) is not bool:
                raise ValueError("boolean temperature quality required")
            if status["temperature_valid"]:
                number(status.get("temperature"), -20, 85)
        log = value.get("log")
        if log is not None:
            if not isinstance(log, dict):
                raise ValueError("log object required")
            identifier(log.get("run_id"))
            identifier(log.get("recipe_id"))
            integer(log.get("revision"), 1, 2147483647)
            integer(log.get("step"), 0, MAX_STEPS)
            if log.get("event") not in {"started", "step", "waiting", "continued", "completed", "aborted", "fault", "power_loss", "sensor_warning", "sensor_recovered", "temperature"}:
                raise ValueError("invalid run event")
            if not isinstance(log.get("message", ""), str) or len(log.get("message", "")) > 160:
                raise ValueError("invalid message")
    ack = value.get("ack")
    if ack is not None:
        if not isinstance(ack, dict):
            raise ValueError("acknowledgement object required")
        identifier(ack.get("id"))
        if ack.get("result") not in {"applied", "rejected"}:
            raise ValueError("invalid acknowledgement")
    return value
