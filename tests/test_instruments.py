import copy
import json
import uuid
from datetime import timedelta, timezone

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
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

    def test_reported_device_id_is_adopted_once_and_cannot_change(self):
        first = self.event()
        first["status"]["device_id"] = "HTR-C82B962D09D7"
        self.device._exchange(first)
        self.assertEqual(self.device.device_id, "HTR-C82B962D09D7")
        changed = self.event(seq=2)
        changed["status"]["device_id"] = "HTR-001122AABBCC"
        with self.assertRaises(ValueError):
            self.device._exchange(changed)

    def test_binding_wizard_reserves_visible_id_in_selected_company(self):
        company = self.env["res.company"].create({"name": "Instrument binding fixture"})
        manager = new_test_user(self.env, login="instrument_bind_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_manager", company_ids=[(6, 0, [company.id])], company_id=company.id)
        wizard = self.env["iot.instrument.bind.wizard"].with_user(manager).create({
            "device_id": "WSH-001122AABBCC", "company_id": company.id})
        wizard.action_search_id()
        self.assertTrue(wizard.validated)
        wizard.name = "Bound washer"
        action = wizard.action_confirm_bind()
        instrument = self.env["iot.instrument"].browse(action["res_id"])
        self.assertEqual(instrument.device_id, "WSH-001122AABBCC")
        self.assertEqual(instrument.uid, instrument.device_id)
        self.assertEqual(instrument.company_id, company)
        self.assertFalse(instrument.token_hash)

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
        receipts = self.env["iot.ingest.event"].search_count([("route", "=", "instrument")])
        self.device._exchange(event)
        self.assertEqual(self.env["iot.instrument.reading"].search_count([("instrument_id", "=", self.device.id)]), 0)
        self.assertEqual(self.env["iot.ingest.event"].search_count([("route", "=", "instrument")]), receipts)

    def test_invalid_and_untimed_samples_cannot_distort_graphs(self):
        self.device._exchange(self.event())
        self.device._exchange(self.event(valid=False, seq=2))
        untimed = self.event(seq=3); untimed["sampled_at"] = 0
        untimed["uptime_ms"] = 300
        untimed["status"]["a"]["temperature"] = 10
        self.device._exchange(untimed)
        unanchored = self.event(seq=1, boot="unanchored"); unanchored["sampled_at"] = 0
        unanchored["status"]["a"]["temperature"] = 20
        self.device._exchange(unanchored)
        model = self.env["iot.instrument.reading"]
        domain = [("instrument_id", "=", self.device.id), ("channel", "=", "a")]
        self.assertEqual(model.search_count(domain), 4)
        self.assertEqual(model.search([("instrument_id", "=", self.device.id), ("device_seq", "=", 3)]).time_quality, "same_boot_estimate")
        self.assertEqual(model.search([("instrument_id", "=", self.device.id), ("device_boot_id", "=", "unanchored")]).time_quality, "unsynchronized")
        self.assertEqual(model._read_group(domain, [], ["temperature:avg"])[0][0], 23.5)
        self.assertEqual(model.read_group(domain, ["temperature:avg"], [])[0]["temperature"], 23.5)

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
        self.assertEqual(program.snapshot["schema"], 2)
        self.assertNotIn("duration_s", program.snapshot["steps"][1])
        self.assertNotIn("duration_s", program.snapshot["steps"][5])
        self.assertEqual(program.snapshot["steps"][3]["duration_s"], 18)
        self.assertEqual(program.snapshot["steps"][6]["duration_s"], 18)

    def test_washer_pump_feedback_and_run_snapshot_are_distinct(self):
        washer = self.env["iot.instrument"].sudo().create({"name": "Local pump fixture", "kind": "washer"})
        event = self.event()
        event["status"] = {"state": "idle", "firmware": "3.5.0-rc1", "pump_timing": {"revision": 2, "a_s": 14, "b_s": 23}}
        event["log"] = {"run_id": "fixture", "recipe_id": "sample", "revision": 2, "step": 1,
            "event": "completed", "pump_timing": {"revision": 1, "a_s": 12, "b_s": 22}}
        washer._exchange(event)
        self.assertEqual((washer.pump_a_seconds, washer.pump_b_seconds, washer.pump_settings_revision), (14, 23, 2))
        log = self.env["iot.instrument.run.log"].search([("instrument_id", "=", washer.id)])
        self.assertEqual(log.pump_timing, event["log"]["pump_timing"])

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
        company = self.env["res.company"].sudo().create({"name": "Catalog lifecycle fixture"})
        self.device.write({"kind": "washer", "company_id": company.id})
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

    def _released_program(self, name="Selection fixture", company=None):
        program = self.env["iot.instrument.recipe"].sudo().create({"name": name,
            "company_id": (company or self.device.company_id).id,
            "step_ids": [(0, 0, {"kind": "home", "sequence": 1}), (0, 0, {"kind": "home", "sequence": 2})]})
        program.action_release()
        return program

    def test_selected_catalog_follows_revisions_and_removals(self):
        self.device.kind = "washer"
        selected = self._released_program()
        self._released_program("Not selected")
        self.device.write({"program_scope": "selected", "assigned_program_ids": [(6, 0, selected.ids)]})
        self.assertEqual([p["id"] for p in json.loads(self.device._program_catalog()[0])["programs"]], [selected.uid])
        revision = self.env["iot.instrument.recipe"].browse(selected.action_new_revision()["res_id"])
        revision.action_release()
        self.assertEqual(json.loads(self.device._program_catalog()[0])["programs"][0]["revision"], 2)
        self.device.assigned_program_ids = revision
        revision.active = False
        self.assertEqual(json.loads(self.device._program_catalog()[0])["programs"], [])
        restored = self.env["iot.instrument.recipe"].browse(revision.action_new_revision()["res_id"])
        restored.write({"active": True})
        restored.action_release()
        self.assertEqual(json.loads(self.device._program_catalog()[0])["programs"][0]["revision"], 3)

    def test_program_selection_rejects_empty_draft_and_other_company(self):
        self.device.kind = "washer"
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.device.write({"program_scope": "selected"})
        draft = self.env["iot.instrument.recipe"].sudo().create({"name": "Draft"})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.device.write({"program_scope": "selected", "assigned_program_ids": [(6, 0, draft.ids)]})
        other = self.env["res.company"].sudo().create({"name": "Other selection company"})
        foreign = self._released_program(company=other)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.device.write({"program_scope": "selected", "assigned_program_ids": [(6, 0, foreign.ids)]})

    def test_program_sync_requires_fresh_device_digest(self):
        self.device.kind = "washer"
        self._released_program()
        _, digest = self.device._program_catalog()
        self.assertEqual(self.device.program_sync_state, "unconnected")
        now = fields.Datetime.now()
        self.device.write({"last_seen": now, "status_sampled_at": now, "status_json": {"catalog_sync": 1}})
        self.assertEqual(self.device.program_sync_state, "pending")
        self.device.status_json = {"catalog_sync": 1, "catalog_digest": digest}
        self.assertEqual(self.device.program_sync_state, "synced")
        self.device.status_sampled_at = now - timedelta(minutes=5)
        self.assertEqual(self.device.program_sync_state, "offline")
        self.device.write({"status_sampled_at": now, "status_json": {}})
        self.assertEqual(self.device.program_sync_state, "unsupported")

    def test_selecting_programs_never_starts_or_queues_device_commands(self):
        self.device.kind = "washer"
        program = self._released_program()
        operator = new_test_user(self.env, login="program_operator_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_operator")
        viewer = new_test_user(self.env, login="program_viewer_" + uuid.uuid4().hex,
            groups="base.group_user,iot_control_center.group_iot_user")
        self.device.with_user(operator).write({"program_scope": "selected", "assigned_program_ids": [(6, 0, program.ids)]})
        notice = self.device.with_user(operator).action_apply_programs()
        self.assertEqual(notice["params"]["type"], "info")
        self.assertFalse(self.device.command_ids)
        self.assertEqual(self.device.state, "uncommissioned")
        with self.assertRaises(AccessError):
            self.device.with_user(viewer).action_apply_programs()
        with self.assertRaises(AccessError):
            self.device.with_user(viewer).write({"program_scope": "all"})

    def test_navigation_and_overview_expose_program_workflow(self):
        root = self.env.ref("iot_control_center.menu_iot_root")
        instruments = self.env.ref("iot_control_center.menu_iot_instruments")
        self.assertEqual(instruments.parent_id, root)
        for name in ("menu_array_washers", "menu_washer_programs", "menu_buffer_heaters"):
            self.assertEqual(self.env.ref("iot_control_center." + name).parent_id, instruments)
        for name in ("menu_iot_mode_cards", "menu_iot_mode_detailed", "menu_iot_openwrt_cards"):
            self.assertFalse(self.env.ref("iot_control_center." + name).active)
        data = self.env["iot.control.board"].get_overview()
        self.assertEqual(len(data["cards"]), 6)
        self.assertEqual([s["key"] for s in data["shortcuts"]], ["programs", "select", "temperatures"])
        for shortcut in data["shortcuts"]:
            self.assertIn(("company_id", "in", self.env.companies.ids), shortcut["action"]["domain"])
