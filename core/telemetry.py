"""Strict, side-effect-free decoding. Receipt time is never regenerated."""
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAX_BODY_BYTES = 2 * 1024 * 1024

@dataclass(frozen=True)
class Measurement:
    node: str
    channel: str
    temperature: float
    humidity: float
    battery: float | None = None

def timestamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed

def envelope(data, now=None):
    if not isinstance(data, dict) or data.get("protocol_version") != 2:
        raise ValueError("protocol_version=2 is required")
    event_id = data.get("event_id", "")
    if not isinstance(event_id, str) or not re.fullmatch(r"[a-f0-9]{32,64}", event_id):
        raise ValueError("invalid event identity")
    milliseconds = data.get("received_at_ms")
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int):
        raise ValueError("received_at_ms is required")
    received_at = datetime.fromtimestamp(milliseconds / 1000, timezone.utc).replace(tzinfo=None)
    if received_at < datetime(2020, 1, 1) or received_at > (now or datetime.now(timezone.utc).replace(tzinfo=None)) + timedelta(minutes=5):
        raise ValueError("receipt time outside accepted bounds")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return event_id, received_at, digest

def measurement(node, channel, temperature, humidity, battery=None):
    node, channel = str(node or "").strip().upper(), str(channel or "").strip().upper()
    if not node or not channel or len(node) > 128 or len(channel) > 64:
        raise ValueError("invalid probe identity")
    if isinstance(temperature, bool) or isinstance(humidity, bool):
        raise ValueError("boolean is not a measurement")
    t, h = float(temperature), float(humidity)
    if not math.isfinite(t) or not math.isfinite(h) or not -100 <= t <= 150 or not 0 <= h <= 100:
        raise ValueError("measurement outside physical bounds")
    if t == 0 and h == 0:
        raise ValueError("invalid gateway zero-pair sample")
    voltage = None if battery is None else float(battery)
    if voltage is not None and (not math.isfinite(voltage) or voltage < 0 or voltage > 100):
        raise ValueError("invalid battery voltage")
    return Measurement(node, channel, t, h, voltage)

def decode_binary(frame):
    if len(frame) < 13 or frame[:2] != b"\xfa\xce":
        raise ValueError("invalid binary frame header")
    words = frame[7]
    if words < 2 or words % 2 or len(frame) != 9 + words * 2:
        raise ValueError("invalid binary frame length")
    if sum(frame[:-1]) & 255 != frame[-1]:
        raise ValueError("binary checksum mismatch")
    node = f"{int.from_bytes(frame[3:5], 'big'):04X}"
    return [measurement(node, f"CH{i + 1:02d}", int.from_bytes(frame[8+i*4:10+i*4], "big", signed=True) / 10,
                        int.from_bytes(frame[10+i*4:12+i*4], "big"), frame[5] / 10) for i in range(words // 2)]

def decode_json(text, received_at):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("gateway payload must be an object")
    probes = data.get("probes")
    if not isinstance(probes, list) or not 1 <= len(probes) <= 64:
        raise ValueError("between 1 and 64 probes are required")
    at = timestamp(data["reported_at"]) if data.get("reported_at") else received_at
    if at > received_at + timedelta(minutes=5):
        raise ValueError("sample time is ahead of receipt time")
    result = [measurement(p.get("node_id") or data.get("node_id") or data.get("gateway_serial"),
                          p.get("probe_code"), p.get("temperature"), p.get("humidity"),
                          p.get("battery_voltage", data.get("battery_voltage"))) for p in probes if isinstance(p, dict)]
    if len(result) != len(probes) or len({(p.node, p.channel) for p in result}) != len(result):
        raise ValueError("invalid or duplicate probe in frame")
    return data, at, result
