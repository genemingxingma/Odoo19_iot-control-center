import copy
import json
import uuid
from datetime import timedelta, timezone

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestInstruments(TransactionCase):
    def setUp(self):
        super().setUp()
        self.device = self.env["iot.instrument"].sudo().create({"name": "Fixture heater", "kind": "heater"})

    def event(self, seconds=0, valid=True, boot="testboot", seq=1):
        stamp = fields.Datetime.now() + timedelta(seconds=seconds)
        return {"protocol": 1, "event_id": uuid.uuid4().hex, "boot_id": boot, "seq": seq,
            "uptime_ms": 100, "sampled_at": int(stamp.replace(tzinfo=timezone.utc).timestamp()), "observation": True,
            "status": {"state": "idle", "firmware": "3.1.0-dev", "hardware": "heater-esp12s-ds18b20-v1",
                "control_interface":"heater-control-v1","local_enable":True,"remote_start":False,
                "rise_window_s":600,"minimum_rise_c":1,"enabled":False,
                "a": {"valid": valid, "temperature": 37, "target": 37, "fault": "none", "output": False}}}

    def test_measurements_are_idempotent(self):
        event = self.event()
        self.device._exchange(event)
        self.device._exchange(event)
        rows = self.env["iot.instrument.reading"].search([("instrument_id", "=", self.device.id)])
        self.assertEqual(len(rows), 1)
        bad = copy.deepcopy(event); bad["status"]["a"]["temperature"] = 39
        with self.assertRaises(ValueError):
            self.device._exchange(bad)

    def test_heartbeat_is_not_a_temperature_sample(self):
        event = self.event(); event["observation"] = False
        self.device._exchange(event)
        self.assertEqual(self.env["iot.instrument.reading"].search_count([("instrument_id", "=", self.device.id)]), 0)

    def test_invalid_and_untimed_samples_cannot_distort_graphs(self):
        self.device._exchange(self.event())
        self.device._exchange(self.event(valid=False, seq=2))
        untimed = self.event(seq=3); untimed["sampled_at"] = 0
        untimed["status"]["a"]["temperature"] = 10
        self.device._exchange(untimed)
        model = self.env["iot.instrument.reading"]
        domain = [("instrument_id", "=", self.device.id), ("channel", "=", "a")]
        self.assertEqual(model.search_count(domain), 3)
        self.assertEqual(model._read_group(domain, [], ["temperature:avg"])[0][0], 37)
        self.assertEqual(model.read_group(domain, ["temperature:avg"], [])[0]["temperature"], 37)

    def test_old_boot_cannot_overwrite_latest_state(self):
        self.device._exchange(self.event())
        old = self.event(seconds=-30, boot="earlierboot", seq=999)
        old["status"]["state"] = "heating"
        self.device._exchange(old)
        self.assertEqual(self.device.state, "idle")
        self.assertEqual(self.device.boot_id, "testboot")

    def test_exact_ack_is_required(self):
        command = self.device._enqueue("set_temperature", {"a": 37, "rise_window_s":600, "minimum_rise_c":1})
        response = self.device._exchange(self.event())
        self.assertEqual(response["command"]["id"], command.uid)
        self.assertEqual(command.state, "sent")
        wrong = self.event(seq=2); wrong["ack"] = {"id": "other-device", "result": "applied"}
        self.device._exchange(wrong)
        self.assertEqual(command.state, "sent")
        exact = self.event(seq=3); exact["ack"] = {"id": command.uid, "result": "applied"}
        self.device._exchange(exact)
        self.assertEqual(command.state, "applied")

    def test_stop_supersedes_and_expiry_prevents_delivery(self):
        first = self.device._enqueue("set_temperature", {"a": 37, "rise_window_s":600, "minimum_rise_c":1})
        stop = self.device._enqueue("stop", {})
        self.assertEqual(first.state, "cancelled")
        stop.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(self.device._exchange(self.event())["command"])
        self.assertEqual(stop.state, "expired")

    def test_platform_defaults_and_device_stored_settings_are_distinct(self):
        self.device.action_set_temperature()
        pending = self.env["iot.instrument.command"].search([("instrument_id", "=", self.device.id)], limit=1)
        self.assertEqual(pending.payload, {"a":37,"rise_window_s":600,"minimum_rise_c":1})
        self.assertFalse(self.device.settings_ready)
        data = self.event()
        data["status"]["settings_ready"] = True
        data["status"]["a"]["target"] = 38
        self.device._exchange(data)
        self.assertTrue(self.device.settings_ready)
        self.assertEqual(self.device.applied_target_a, 38)
        self.assertEqual(self.device.target_a, 37)
        self.assertTrue(self.device.settings_pending)
        self.assertEqual(self.device.applied_rise_window_s, 600)
        self.assertEqual(self.device.applied_minimum_rise_c, 1)

    def test_heater_alarm_replay_is_not_an_extra_temperature_sample(self):
        data = self.event(); data["observation"] = False; data["alarm"] = True
        data["status"]["state"] = "fault"; data["status"]["a"]["fault"] = "no_rise"
        self.device._exchange(data); self.device._exchange(data)
        rows = self.env["iot.instrument.alarm"].search([("instrument_id", "=", self.device.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.fault, "no_rise")
        self.assertEqual(self.device.fault_a, "no_rise")
        self.assertEqual(self.env["iot.instrument.reading"].search_count([("instrument_id", "=", self.device.id)]), 0)
        user = new_test_user(self.env, login="alarmread_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_user")
        with self.assertRaises(AccessError): rows.with_user(user).write({"fault":"none"})

    def test_washer_temperature_warning_is_recorded_without_fault_state(self):
        washer = self.env["iot.instrument"].sudo().create({"name":"Timed washer", "kind":"washer"})
        data = self.event(); data["observation"] = False
        data["status"] = {"state":"running", "firmware":"3.0.1-dev", "temperature_valid":False}
        data["log"] = {"run_id":"offline-run", "recipe_id":"timed-program", "revision":1, "step":1,
            "event":"sensor_warning", "message":"Temperature unavailable; timed program continues"}
        washer._exchange(data)
        self.assertEqual(washer.state, "running")
        self.assertFalse(washer.washer_temperature_valid)
        row = self.env["iot.instrument.run.log"].search([("instrument_id", "=", washer.id)])
        self.assertFalse(row.temperature_valid)
        data = copy.deepcopy(data); data["event_id"] = uuid.uuid4().hex; data["seq"] = 2
        data["status"].update(temperature_valid=True,temperature=37.25)
        data["log"]["event"] = "sensor_recovered"
        washer._exchange(data)
        self.assertEqual(washer.washer_temperature, 37.25)
        self.assertEqual(washer.state, "running")

    def test_readonly_and_cross_company_control_denied(self):
        user = new_test_user(self.env, login="instrument_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_user")
        with self.assertRaises(AccessError):
            self.device.with_user(user).action_stop()
        operator = new_test_user(self.env, login="instrument_op_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_operator")
        company = self.env["res.company"].create({"name": "Other instrument company"})
        other = self.env["iot.instrument"].sudo().create({"name": "Other", "kind": "heater", "company_id": company.id})
        with self.assertRaises(AccessError):
            other.with_user(operator).action_stop()
        with self.assertRaises(AccessError):
            self.device.with_user(operator).write({"state": "idle"})

    def test_released_recipe_and_steps_are_immutable_and_copyable(self):
        manager = new_test_user(self.env, login="instrument_mgr_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_manager")
        program = self.env["iot.instrument.recipe"].with_user(manager).create({"name": "Fixture", "step_ids": [
            (0, 0, {"kind": kind, "sequence": i, "duration_s": 10, "rps": 1 if kind in {"wash", "dry"} else 0})
            for i, kind in enumerate(["home", "fill_a", "wash", "drain", "dry", "home"])]})
        program.action_release()
        self.assertTrue(program.checksum)
        self.assertNotIn("temperature_min", program.snapshot)
        self.assertNotIn("temperature_max", program.snapshot)
        with self.assertRaises(UserError): program.write({"name": "Changed"})
        with self.assertRaises(UserError): program.step_ids[:1].write({"duration_s": 20})
        duplicate = program.copy()
        self.assertEqual(duplicate.state, "draft")
        self.assertNotEqual(duplicate.uid, program.uid)

    def test_typical_program_gets_automatic_homing_and_keeps_both_fills(self):
        manager = new_test_user(self.env, login="typical_program_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_manager")
        kinds = ["fill_a", "wait", "wash", "drain", "fill_b", "wash", "drain", "dry"]
        program = self.env["iot.instrument.recipe"].with_user(manager).create({
            "name": "General Microarray V1.0", "device_label": "General Microarray V1.0",
            "step_ids": [(0, 0, {"kind": kind, "sequence": index * 10,
                "duration_s": 10, "rps": 1 if kind == "wash" else 10 if kind == "dry" else 0,
                "cycles": 3 if kind == "wash" else 0, "reverse_s": 3})
                for index, kind in enumerate(kinds, 1)]})
        program.action_release()
        self.assertEqual([step["kind"] for step in program.snapshot["steps"]], ["home", *kinds])
        self.assertEqual(program.snapshot["steps"][3]["duration_s"], 18)
        self.assertEqual(program.snapshot["steps"][6]["duration_s"], 18)

    def test_original_motor_defaults_do_not_replace_explicit_speeds(self):
        manager = new_test_user(self.env, login="motor_defaults_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_manager")
        recipe = self.env["iot.instrument.recipe"].with_user(manager).create({"name": "Motor baseline"})
        steps = self.env["iot.instrument.recipe.step"].with_user(manager).create([
            {"recipe_id": recipe.id, "kind": "wash"},
            {"recipe_id": recipe.id, "kind": "dry"},
            {"recipe_id": recipe.id, "kind": "wash", "rps": 0.5},
        ])
        self.assertEqual(steps.mapped("rps"), [1.0, 10.0, 0.5])
        steps[0].write({"kind": "wait"})
        self.assertEqual(steps[0].rps, 0)
        steps[0].write({"kind": "dry"})
        self.assertEqual(steps[0].rps, 10)
        steps[0].write({"kind": "wash", "rps": 0.75})
        self.assertEqual(steps[0].rps, 0.75)
        draft = self.env["iot.instrument.recipe.step"].new({"kind": "dry"})
        draft._onchange_kind_speed()
        self.assertEqual(draft.rps, 10)

    def test_authoritative_catalog_revision_archive_and_company(self):
        self.device.kind = "washer"
        programs=self.env["iot.instrument.recipe"].sudo()
        created=programs.browse()
        for i in range(5):
            p=programs.create({"name": f"Catalog {i}", "company_id": self.device.company_id.id,
                "step_ids": [(0,0,{"kind":"home","sequence":1}),(0,0,{"kind":"home","sequence":2})]})
            p.action_release(); created|=p
        body, before=self.device._program_catalog()
        catalog=json.loads(body)
        self.assertTrue({p.uid for p in created} <= {p["id"] for p in catalog["programs"]})
        action=created[0].action_new_revision()
        revision=programs.browse(action["res_id"])
        # Editing an unpublished revision must not replace the offline program.
        self.assertEqual(self.device._program_catalog()[1], before)
        revision.write({"device_label": "Updated wash"})
        revision.action_release()
        body, after=self.device._program_catalog()
        self.assertNotEqual(before,after)
        self.assertEqual(next(p["revision"] for p in json.loads(body)["programs"] if p["id"]==created[0].uid),2)
        revision.write({"active":False})
        body,_=self.device._program_catalog()
        self.assertNotIn(revision.uid,{p["id"] for p in json.loads(body)["programs"]})
        other_company=self.env["res.company"].sudo().create({"name":"Catalog isolation fixture"})
        foreign=programs.create({"name":"Other company program","company_id":other_company.id,
            "step_ids":[(0,0,{"kind":"home","sequence":1}),(0,0,{"kind":"home","sequence":2})]})
        foreign.action_release()
        self.assertEqual(self.device._program_catalog()[0], body)
        created.write({"active":False})
        empty=json.loads(self.device._program_catalog()[0])
        self.assertEqual(empty["programs"],[])
        self.assertTrue(empty["complete"])
