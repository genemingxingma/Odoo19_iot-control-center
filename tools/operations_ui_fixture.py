"""Synthetic UI fixture for the disposable, network-isolated local database."""
from datetime import timedelta

from odoo import Command, fields
from odoo.tools.translate import code_translations

assert env.cr.dbname == "iot_ui_test_20260906"
env["ir.cron"].search([]).write({"active": False})
env["ir.mail_server"].search([]).write({"active": False})
env["ir.config_parameter"].sudo().set_param("iot_control_center.middleware_base_url", "")
env.company.write({"name": "IoT UI / Synthetic Lab", "country_id": env.ref("base.th").id})
env.company.partner_id.tz = "Asia/Bangkok"
langs = env["res.lang"].with_context(active_test=False).search([("code", "in", ["zh_CN", "th_TH"])])
env["base.language.install"].create({"lang_ids": [Command.set(langs.ids)], "overwrite": True}).lang_install()
env.ref("base.user_admin").write({"lang": "zh_CN", "tz": "Asia/Bangkok"})
now = fields.Datetime.now()
if not env["iot.th.gateway"].search_count([("serial", "=", "UI-FIXTURE")]):
    gateway = env["iot.th.gateway"].create({"name": "Synthetic gateway", "serial": "UI-FIXTURE", "company_id": env.company.id})
    for index, name in enumerate(["Sample refrigerator A", "Reagent storage B", "Room humidity C"]):
        sensor = env["iot.th.sensor"].create({"name": name, "gateway_id": gateway.id,
            "node_id": f"AB0{index}", "probe_code": "CH01", "company_id": env.company.id})
        env["iot.th.reading"].create([{"sensor_id": sensor.id, "gateway_id": gateway.id,
            "temperature": 5 + index * 2 + (hour % 4) / 10, "humidity": 50 + hour % 6,
            "reported_at": now - timedelta(hours=hour + (2 if index == 2 else 0))} for hour in range(24)])
    env["iot.device"].create([
        {"name": "Synthetic ventilation relay", "serial": "UI-RELAY-1", "company_id": env.company.id,
         "relay_state": "on", "desired_relay_state": "off", "relay_command_state": "pending", "last_seen": now},
        {"name": "Synthetic lighting relay", "serial": "UI-RELAY-2", "company_id": env.company.id,
         "relay_state": "off", "last_seen": now - timedelta(hours=2)}])
    terminal = env["iot.attendance.device"].create({"name": "Synthetic attendance terminal",
        "serial_number": "UI-ATTENDANCE", "protocol": "adms_http", "company_id": env.company.id})
    terminal._ingest_adms_payload("999\t2026-09-06 08:00:00\t0\t1", "ATTLOG")
for sensor in env["iot.th.sensor"].search([("gateway_id.serial", "=", "UI-FIXTURE")]):
    latest = env["iot.th.reading"].search([("sensor_id", "=", sensor.id)], order="reported_at desc", limit=1)
    sensor.write({"last_temperature": latest.temperature, "last_humidity": latest.humidity,
                  "last_reported_at": latest.reported_at})
for language in ("zh_CN", "th_TH"):
    messages = {m["id"]: m["string"] for m in code_translations.get_web_translations("iot_control_center", language)["messages"]}
    assert messages["Operations Overview"] != "Operations Overview"
    assert messages["Refresh overview"] != "Refresh overview"
    data = env["iot.control.board"].with_context(lang=language).get_overview()
    assert data["cards"][0]["title"] != "Relay Control"
    assert env["iot.attendance.device"].with_context(lang=language).fields_get(["pending_count"])["pending_count"]["string"] != "Needs Review"
    terminal = env["iot.attendance.device"].search([("serial_number", "=", "UI-ATTENDANCE")])
    assert terminal.with_context(lang=language).display_last_sync_message != terminal.last_sync_message
    print("RUNTIME_TRANSLATIONS_OK", language)
print("OVERVIEW_ACTION", env.ref("iot_control_center.action_iot_operations_overview").id)
print("SENSOR_ACTION", env.ref("iot_control_center.action_iot_th_sensor").id)
print("ATTENDANCE_ACTION", env.ref("iot_control_center.action_iot_attendance_device").id)
print("RELAY_ACTION", env.ref("iot_control_center.action_iot_device").id)
env.cr.commit()
