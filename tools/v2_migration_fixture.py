"""Run by odoo shell, only against the named disposable migration database."""
import json
import os
import secrets
import time
import uuid
from datetime import timedelta
from odoo import fields

assert env.cr.dbname == "iot_v2_migration_20260906", "Isolated database required"
phase = os.environ["IOT_FIXTURE_PHASE"]
params = env["ir.config_parameter"].sudo()
if phase == "seed":
    params.set_param("iot_control_center.middleware_enabled", "True")
    params.set_param("iot_control_center.middleware_base_url", "")
    params.set_param("iot_control_center.mqtt_enabled", "False")
    params.set_param("iot_control_center.th_tcp_enabled", "False")
    env["ir.cron"].search([]).write({"active": False})
    partner = env["res.partner"].create({"name": "V2 migration preservation fixture"})
    employee = env["hr.employee"].create({"name": "V2 synthetic employee", "company_id": env.company.id})
    attendance = env["hr.attendance"].create({"employee_id": employee.id,
        "check_in": fields.Datetime.now() - timedelta(hours=2), "check_out": fields.Datetime.now() - timedelta(hours=1)})
    gateway = env["iot.th.gateway"].create({"name": "V1 fixture", "serial": "V1-FIXTURE", "company_id": env.company.id})
    sensor = env["iot.th.sensor"].create({"name": "Named migration probe", "gateway_id": gateway.id,
        "company_id": env.company.id, "node_id": "ABCD", "probe_code": "CH01"})
    env["iot.th.reading"].create([
        {"sensor_id": sensor.id, "gateway_id": gateway.id, "temperature": 5, "humidity": 55,
         "reported_at": fields.Datetime.now() - timedelta(hours=4)},
        {"sensor_id": sensor.id, "gateway_id": gateway.id, "temperature": 10, "humidity": 60,
         "reported_at": fields.Datetime.now() - timedelta(hours=5), "is_hourly_rollup": True, "sample_count": 10},
    ])
    params.set_param("iot_v2.fixture_ids", json.dumps({"partner": partner.id, "employee": employee.id,
        "attendance": attendance.id, "gateway": gateway.id, "sensor": sensor.id}))
    env.cr.commit()
    print("V1_FIXTURE_SEEDED")
elif phase == "authorize":
    assert env["iot.th.reading"].search_count([]) == 2, "Failed upgrade must preserve history"
    assert env["ir.module.module"].search([("name", "=", "iot_control_center")]).latest_version == "19.0.1.0.19"
    params.set_param("iot_control_center.v2_discard_monitoring_history", "true")
    env.cr.commit()
    print("V1_GATE_ROLLBACK_AND_TEST_AUTHORIZATION_OK")
elif phase == "verify":
    from odoo.addons.iot_control_center.services.tcp_service import TCPIngestService
    ids = json.loads(params.get_param("iot_v2.fixture_ids"))
    for key, model in [("partner", "res.partner"), ("employee", "hr.employee"), ("attendance", "hr.attendance"),
                       ("gateway", "iot.th.gateway"), ("sensor", "iot.th.sensor")]:
        assert env[model].browse(ids[key]).exists(), f"Unrelated data lost: {key}"
    assert env["iot.th.sensor"].browse(ids["sensor"]).name == "Named migration probe"
    assert env["iot.th.reading"].search_count([]) == 0
    assert env["iot.th.alert"].search_count([]) == 0
    gateway = env["iot.th.gateway"].browse(ids["gateway"])
    token = secrets.token_hex(24)
    gateway.tcp_token = token
    env.cr.commit()
    service = TCPIngestService(env.cr.dbname)
    event = {"protocol_version": 2, "event_id": uuid.uuid4().hex, "received_at_ms": int(time.time() * 1000),
        "payload_text": json.dumps({"gateway_serial": gateway.serial, "token": token,
            "probes": [{"node_id": "ABCD", "probe_code": "CH01", "temperature": 6, "humidity": 56}]})}
    assert service.ingest(event)["samples"] == 1
    assert service.ingest(event)["duplicate"] is True
    changed = {**event, "payload_text": event["payload_text"].replace('"temperature": 6', '"temperature": 7')}
    try:
        service.ingest(changed)
        raise AssertionError("Changed content reused a committed identity")
    except ValueError:
        pass
    env.cr.rollback()
    env.invalidate_all()
    assert env["iot.th.reading"].search_count([]) == 1
    assert env["iot.ingest.event"].search_count([]) == 1
    print("V2_MIGRATION_PRESERVATION_AND_REAL_INGEST_REPLAY_OK")
else:
    raise AssertionError("Unknown fixture phase")
