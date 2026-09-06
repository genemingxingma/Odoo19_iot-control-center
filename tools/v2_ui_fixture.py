"""Synthetic browser fixtures, never executable against a production database."""
from datetime import timedelta
from odoo import Command, fields

assert env.cr.dbname == "iot_v2_isolated_20260906"
env["ir.cron"].search([]).write({"active": False})
params = env["ir.config_parameter"].sudo()
params.set_param("iot_control_center.middleware_base_url", "")
params.set_param("mail.catchall.domain", "example.invalid")
env["ir.mail_server"].search([]).write({"active": False})
langs = env["res.lang"].with_context(active_test=False).search([("code", "in", ["zh_CN", "th_TH"])])
env["base.language.install"].create({"lang_ids": [Command.set(langs.ids)], "overwrite": True}).lang_install()
env.ref("base.user_admin").write({"lang": "zh_CN", "tz": "Asia/Bangkok"})
env.company.country_id = env.ref("base.th")
gateway = env["iot.th.gateway"].search([("serial", "=", "UI-FIXTURE")], limit=1)
if not gateway:
    gateway = env["iot.th.gateway"].create({"name": "隔离测试网关", "serial": "UI-FIXTURE", "company_id": env.company.id})
    for index, name in enumerate(["样本冷藏柜 A", "试剂储存区 B"]):
        sensor = env["iot.th.sensor"].create({"name": name, "gateway_id": gateway.id, "node_id": f"AB0{index}",
            "probe_code": "CH01", "company_id": env.company.id, "location_detail": "合成数据，非真实监测"})
        env["iot.th.reading"].create([{"sensor_id": sensor.id, "gateway_id": gateway.id,
            "temperature": 5 + index * 2 + (hour % 4) / 10, "humidity": 50 + hour % 6,
            "reported_at": fields.Datetime.now() - timedelta(hours=hour)} for hour in range(24)])
for lang in ("zh_CN", "th_TH", "en_US"):
    info = env["iot.th.sensor"].with_context(lang=lang).fields_get(["name"])
    print("UI_FIELD_LABEL", lang, info["name"]["string"])
print("UI_ACTION_ID", env.ref("iot_control_center.action_iot_th_reading").id)
env.cr.commit()
