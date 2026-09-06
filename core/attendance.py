"""Attendance wire parsing, independent of Odoo and employee matching."""
from datetime import datetime


def first_value(payload, *keys):
    return next((payload[key] for key in keys if payload.get(key) not in (None, "")), None)


def normalize_direction(direction, status=None, mode="device"):
    if mode == "auto" or str(direction).strip().lower() == "auto":
        return "auto"
    mapping = {"0": "in", "1": "out", "2": "out", "3": "in", "4": "in", "5": "out",
               "in": "in", "check_in": "in", "out": "out", "check_out": "out"}
    value = direction if direction not in (None, "") else status
    return mapping.get(str(value).strip().lower(), "auto")


def parse_timestamp(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing punch timestamp")
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def parse_adms_line(line, table_name):
    table = (table_name or "").strip().upper()
    # Photo, user and operation tables are not attendance events, even when
    # their metadata happens to contain a PIN and a timestamp.
    if table not in ("", "ATTLOG"):
        return None
    parts = line.strip("\r\n").split("\t")
    kv = {}
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            kv[key.strip().lower()] = value.strip()
    if kv:
        pin = first_value(kv, "pin", "userid", "enrollnumber")
        timestamp = first_value(kv, "datetime", "time", "time_second")
        status = first_value(kv, "status", "attstatus")
        verification = first_value(kv, "verify", "verifymode")
    elif len(parts) >= 2:
        pin, timestamp = parts[0].strip(), parts[1].strip()
        # Empty fields must retain their positions. STATUS is the direction;
        # VERIFY is password/fingerprint/card/etc, never a direction.
        status = parts[2].strip() if len(parts) > 2 else None
        verification = parts[3].strip() if len(parts) > 3 else None
    else:
        if not table:
            return None
        raise ValueError("Malformed attendance row")
    if not pin or not timestamp:
        if not table:
            return None
        raise ValueError("Missing attendance PIN or timestamp")
    parse_timestamp(timestamp)
    return {"device_user_id": pin, "timestamp": timestamp, "direction": status,
            "status": status, "verification": verification}
