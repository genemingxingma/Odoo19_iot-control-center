"""Native card-layout fixtures; run only in the disposable release test database.

The browser harness supplies ui_password in memory through the shell's stdin.
No fixture is bound to a physical device, and all external delivery stays off.
"""
import json
from odoo import Command, fields
from odoo.tests.common import new_test_user

assert env.cr.dbname == "iot_release_588c072_test"
assert isinstance(ui_password, str) and len(ui_password) >= 32
# Unavailable social integrations in this disposable database must not trigger
# registry rebuilds on every preview request. None has ever been installed here.
pending = env["ir.module.module"].search([("state", "=", "to install"), ("name", "in", [
    "social_facebook", "social_instagram", "social_linkedin", "social_twitter", "social_youtube"])])
pending.write({"state": "uninstalled"})
env["ir.cron"].search([]).write({"active": False})
env["ir.mail_server"].search([]).write({"active": False})
env["ir.config_parameter"].sudo().set_param("iot_control_center.middleware_base_url", "")
languages = env["res.lang"].with_context(active_test=False).search([("code", "in", ["zh_CN", "th_TH"]), ("active", "=", False)])
if languages:
    env["base.language.install"].create({"lang_ids": [Command.set(languages.ids)]}).lang_install()
company = env["res.company"].search([("name", "=", "Relay Layout / Synthetic Only")], limit=1)
if not company:
    company = env["res.company"].create({"name": "Relay Layout / Synthetic Only", "country_id": env.ref("base.th").id})
location = env["stock.location"].search([("name", "=", "Synthetic room"), ("company_id", "=", company.id)], limit=1)
if not location:
    location = env["stock.location"].create({"name": "Synthetic room", "company_id": company.id})
long_location = env["stock.location"].search([("name", "=", "Long synthetic room " * 8), ("company_id", "=", company.id)], limit=1)
if not long_location:
    long_location = env["stock.location"].create({"name": "Long synthetic room " * 8, "company_id": company.id})
cases = [
    ("01 Empty metadata", False, False),
    ("02 Detail only", "Pass box sample to waste", False),
    ("03 Room only", False, location.id),
    ("04 Complete metadata", "Washing buffer heater", location.id),
    ("05 Long metadata", "Long position description " * 15 + "\n<b>Plain text, not markup</b>", long_location.id),
    ("06 Long device name " * 10, "\u957f\u4f4d\u7f6e\u8bf4\u660e" * 30 + "\n" + "\u0e23\u0e32\u0e22\u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14\u0e15\u0e33\u0e41\u0e2b\u0e19\u0e48\u0e07" * 10, location.id),
]
for index, (name, detail, room) in enumerate(cases):
    serial = "SYNTHETIC-LAYOUT-" + str(index)
    values = {"name": name, "serial": serial, "company_id": company.id,
              "location_detail": detail, "location_id": room, "relay_state": "off",
              "desired_relay_state": "off", "relay_command_state": "confirmed", "last_seen": fields.Datetime.now()}
    device = env["iot.device"].with_context(active_test=False).search([("serial", "=", serial)], limit=1)
    if device:
        device.write(values)
    else:
        env["iot.device"].create(values)
for lang in ("en_US", "zh_CN", "th_TH"):
    login = "synthetic-layout-" + lang
    user = env["res.users"].search([("login", "=", login)], limit=1)
    values = {"password": ui_password, "lang": lang, "tz": "Asia/Bangkok",
              "company_id": company.id, "company_ids": [Command.set(company.ids)]}
    if user:
        user.write(values)
    else:
        fixture_env = env(context=dict(env.context, no_reset_password=True, tracking_disable=True))
        new_test_user(fixture_env, login=login, groups="base.group_user,base.group_erp_manager,iot_control_center.group_iot_operator", **values)
env.cr.commit()
print("RELAY_LAYOUT_FIXTURE_OK", json.dumps({"action": env.ref("iot_control_center.action_iot_device_cards").id, "cards": len(cases)}))
