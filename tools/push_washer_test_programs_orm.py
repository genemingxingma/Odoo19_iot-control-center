"""Publish two bounded washer commissioning programs without starting a run."""

import json
import os

from odoo.addons.iot_control_center.core import instruments as contract


DATABASE = "odoo-26-1-16"
MODULE_VERSION = "19.0.2.5.0"
PROGRAMS = (
    {
        "uid": "washer_test_wet_path_v1",
        "name": "Commissioning Test 1 - Wet Path",
        "label": "TEST 1 - Wet Path",
        "revision": 1,
        "steps": (
            {"kind": "fill_a", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wait", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wash", "duration_s": 12, "rps": 1.0, "reverse_s": 3, "cycles": 2},
            {"kind": "drain", "duration_s": 20, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "fill_b", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wait", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wash", "duration_s": 12, "rps": 1.0, "reverse_s": 3, "cycles": 2},
            {"kind": "drain", "duration_s": 20, "rps": 0, "reverse_s": 5, "cycles": 0},
        ),
    },
    {
        "uid": "washer_test_full_cycle_v1",
        "name": "Commissioning Test 2 - Full Cycle",
        "label": "TEST 2 - Full Cycle",
        "revision": 1,
        "steps": (
            {"kind": "fill_a", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wait", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wash", "duration_s": 30, "rps": 1.0, "reverse_s": 3, "cycles": 5},
            {"kind": "drain", "duration_s": 20, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "fill_b", "duration_s": 30, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "wash", "duration_s": 30, "rps": 1.0, "reverse_s": 3, "cycles": 5},
            {"kind": "drain", "duration_s": 20, "rps": 0, "reverse_s": 5, "cycles": 0},
            {"kind": "dry", "duration_s": 15, "rps": 10.0, "reverse_s": 5, "cycles": 0},
        ),
    },
)


def payload(spec):
    steps = []
    for step in spec["steps"]:
        item = dict(step)
        if item["kind"] in ("fill_a", "fill_b"):
            item.pop("duration_s")
        steps.append(item)
    return contract.recipe({
        "schema": 2,
        "id": spec["uid"],
        "label": spec["label"],
        "revision": spec["revision"],
        "steps": steps,
    })


def step_rows(record):
    return tuple({
        "kind": step.kind,
        "duration_s": step.duration_s,
        "rps": step.rps,
        "reverse_s": step.reverse_s,
        "cycles": step.cycles,
    } for step in record.step_ids.sorted("sequence"))


assert env.cr.dbname == DATABASE
mode = os.environ["WASHER_PROGRAM_MODE"]
assert mode in ("inspect", "apply", "verify")
module = env["ir.module.module"].sudo().search([("name", "=", "iot_control_center")])
assert len(module) == 1 and module.latest_version == MODULE_VERSION
devices = env["iot.instrument"].sudo().with_context(active_test=False).search([
    ("kind", "=", "washer"), ("active", "=", True),
])
assert len(devices) == 1, "Expected exactly one active washer"
device = devices.ensure_one()
recipe_model = env["iot.instrument.recipe"].sudo().with_context(active_test=False)
command_model = env["iot.instrument.command"].sudo().with_context(active_test=False)
expected = {spec["uid"]: payload(spec) for spec in PROGRAMS}
targets = recipe_model.browse()

if mode == "apply":
    before_commands = command_model.search_count([])
    for spec in PROGRAMS:
        records = recipe_model.search([
            ("company_id", "=", device.company_id.id), ("uid", "=", spec["uid"]),
        ])
        assert len(records) <= 1, "Unexpected duplicate commissioning program"
        if records:
            target = records.ensure_one()
            assert target.revision == spec["revision"]
            assert target.name == spec["name"] and target.device_label == spec["label"]
            assert target.active and step_rows(target) == spec["steps"]
            if target.state == "draft":
                target.action_release()
        else:
            target = recipe_model.create({
                "name": spec["name"],
                "device_label": spec["label"],
                "uid": spec["uid"],
                "revision": spec["revision"],
                "company_id": device.company_id.id,
                "step_ids": [(0, 0, {"sequence": index * 10, **step})
                             for index, step in enumerate(spec["steps"], start=1)],
            })
            target.action_release()
        assert target.state == "released" and target.snapshot == expected[spec["uid"]]
        targets |= target
    if device.program_scope == "selected":
        device.write({"assigned_program_ids": [(4, target.id) for target in targets]})
    device.action_apply_programs()
    assert command_model.search_count([]) == before_commands, "Publishing must not create a device command"
    env.cr.commit()

if mode in ("apply", "verify"):
    targets = recipe_model.search([
        ("company_id", "=", device.company_id.id),
        ("uid", "in", [spec["uid"] for spec in PROGRAMS]),
    ])
    assert len(targets) == len(PROGRAMS)
    for target in targets:
        assert target.active and target.state == "released"
        assert target.snapshot == expected[target.uid]
    if device.program_scope == "selected":
        assert targets <= device.assigned_program_ids

body, expected_digest = device._program_catalog()
catalog = json.loads(body)
reported_digest = (device.status_json or {}).get("catalog_digest")
result = {
    "mode": mode,
    "module_version": module.latest_version,
    "program_scope": device.program_scope,
    "catalog_count": catalog["count"],
    "catalog_labels": [program["label"] for program in catalog["programs"]],
    "expected_digest": expected_digest,
    "reported_digest": reported_digest,
    "sync_matches": expected_digest == reported_digest,
    "online": device.online,
    "status_fresh": device.status_fresh,
    "firmware": device.firmware,
    "device_program_count": (device.status_json or {}).get("program_count"),
    "created_programs": [
        {"label": expected[spec["uid"]]["label"], "steps": expected[spec["uid"]]["steps"]}
        for spec in PROGRAMS
    ],
}
print("WASHER_TEST_PROGRAM_RESULT", json.dumps(result, ensure_ascii=True, sort_keys=True))
env.cr.rollback()
