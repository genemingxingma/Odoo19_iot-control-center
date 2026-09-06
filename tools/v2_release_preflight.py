"""Read-only release inventory through an existing Odoo shell environment."""
import json
from collections import Counter

module = env["ir.module.module"].search([("name", "=", "iot_control_center")], limit=1)
print("MODULE", json.dumps({"database": env.cr.dbname, "state": module.state, "version": module.latest_version}))
for model in ("iot.device", "iot.th.gateway", "iot.th.sensor", "iot.th.reading", "iot.th.alert", "iot.openwrt.ap"):
    print("COUNT", model, env[model].with_context(active_test=False).search_count([]))
devices = env["iot.device"].with_context(active_test=False).search([])
print("FIRMWARE_COUNTS", json.dumps(dict(Counter(devices.mapped("firmware_version"))), ensure_ascii=False))
for device in devices:
    values = {"id": device.id, "name": device.name, "active": device.active,
        "company": device.company_id.id, "firmware": device.firmware_version,
        "relay_state": device.relay_state, "last_seen": str(device.last_seen),
        "delay_active": device.delay_active, "max_on_minutes": device.max_continuous_on_minutes}
    for name in ("firmware_hardware_profile", "schedule_sync_state", "network_config_dirty"):
        if name in device._fields:
            values[name] = device[name]
    print("RELAY", json.dumps(values, ensure_ascii=False))
for gateway in env["iot.th.gateway"].with_context(active_test=False).search([]):
    print("GATEWAY", json.dumps({"id": gateway.id, "serial": gateway.serial,
        "company": gateway.company_id.id, "active": gateway.active, "last_seen": str(gateway.last_seen),
        "has_json_token": bool(gateway.tcp_token)}, ensure_ascii=False))
for sensor in env["iot.th.sensor"].with_context(active_test=False).search([]):
    print("SENSOR", json.dumps({"id": sensor.id, "name": sensor.name,
        "company": sensor.company_id.id, "gateway": sensor.gateway_id.id,
        "active": sensor.active}, ensure_ascii=False))
params = env["ir.config_parameter"].sudo()
for key in ("middleware_enabled", "middleware_base_url", "th_tcp_host", "th_tcp_port", "mqtt_host", "mqtt_port", "mqtt_topic_root"):
    value = params.get_param("iot_control_center." + key)
    # Endpoint strings can contain administrator-supplied userinfo or tokens.
    if key in ("middleware_base_url", "mqtt_host", "th_tcp_host"):
        value = "configured" if value else "unset"
    print("CONFIG", key, value)
for company in env["res.company"].search([]):
    print("COMPANY", json.dumps({"id": company.id, "country": company.country_id.code,
        "has_internal_host": bool(company.iot_internal_host), "prefer_internal": company.iot_prefer_internal_network}))
messages = env["iot.mqtt.message"].search([], order="id desc", limit=1000)
print("MQTT_RECENT_STATUS", json.dumps(dict(Counter(messages.mapped("state")))))
env.cr.rollback()
