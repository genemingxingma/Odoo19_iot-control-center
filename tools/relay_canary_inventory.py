"""Read-only, allowlisted canary inventory in an authorized Odoo shell."""
import json

from odoo import fields

print("CANARY_INVENTORY_AT", str(fields.Datetime.now()))
for device in env["iot.device"].with_context(active_test=False).search([]):
    schedules = env["iot.schedule"].search(["|", ("device_id", "=", device.id),
                                           ("group_id", "in", device.group_ids.ids)])
    messages = env["iot.mqtt.message"].search([("device_id", "=", device.id)], order="id desc", limit=1)
    payload = {}
    if messages:
        try:
            raw = json.loads(messages.payload)
            payload = {key: raw.get(key) for key in (
                "state", "firmware", "version", "firmware_version", "protocol_version",
                "board_profile", "hardware_profile", "time_synced", "control_inhibit", "mqtt_route",
                "schedule_count", "max_on_sec", "delay_active", "safety_trip", "flash_real_size",
                "free_sketch_space", "sketch_size", "uptime_sec", "relay_pin", "relay_active_low") if key in raw}
        except (ValueError, TypeError):
            pass
    print("CANARY_DEVICE", json.dumps({"id": device.id, "serial": device.serial, "name": device.name,
        "active": device.active, "online": device.online, "company": device.company_id.id,
        "location": device.location_id.display_name, "location_detail": device.location_detail,
        "department": device.department_id.display_name, "groups": device.group_ids.mapped("name"),
        "state": device.relay_state, "last_seen": str(device.last_seen), "firmware": device.firmware_version,
        "hardware": device.firmware_hardware_profile, "flash_bytes": device.flash_real_size_bytes,
        "max_on_minutes": device.max_continuous_on_minutes, "delay_active": device.delay_active,
        "schedules": [{"id": item.id, "command": item.command, "hour": item.hour,
                       "minute": item.minute} for item in schedules],
        "latest_report": payload}, ensure_ascii=False))
print("FIRMWARE_INVENTORY", json.dumps(env["iot.firmware"].search([]).read(
    ["id", "name", "version", "company_id", "image_compatible", "quarantined", "checksum"]), ensure_ascii=False))
env.cr.rollback()
