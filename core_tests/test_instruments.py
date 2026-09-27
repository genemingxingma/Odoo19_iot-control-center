import copy
import json
import unittest
from core import instruments as c


def program():
    return {"schema": 1, "id": "wash-v1", "revision": 1,
        "steps": [{"kind": k, "duration_s": 10, "rps": 1 if k in {"wash", "dry"} else 0}
            for k in ("fill_a", "wait", "wash", "drain", "fill_b", "wash", "drain", "dry")]}


class InstrumentContractTests(unittest.TestCase):
    def test_visible_device_identity_is_type_scoped(self):
        self.assertEqual(c.device_identity("HTR-C82B962D09D7", "heater"), "HTR-C82B962D09D7")
        self.assertEqual(c.device_kind("WSH-001122AABBCC"), "washer")
        for value in ("HTR-2D09D7", "htr-C82B962D09D7", "WSH-001122AABBZZ"):
            with self.assertRaises(ValueError):
                c.device_identity(value)
        with self.assertRaises(ValueError):
            c.device_identity("HTR-C82B962D09D7", "washer")

    def test_discovery_contract_contains_no_company_or_country(self):
        value = c.discovery({"schema": 1, "device_id": "HTR-C82B962D09D7", "kind": "heater",
            "hardware": c.HEATER_HARDWARE, "firmware": "3.2.0-rc4", "company_id": 99, "country": "TH"})
        self.assertEqual(set(value), {"device_id", "kind", "hardware", "firmware"})
        self.assertNotIn("company_id", value)
        self.assertNotIn("country", value)

    def test_device_local_fill_schema(self):
        p = program()
        p["schema"] = 2
        for step in p["steps"]:
            if step["kind"].startswith("fill"):
                del step["duration_s"]
        normalized = c.recipe(p)
        self.assertEqual(c.recipe(normalized), normalized)
        self.assertEqual(normalized["schema"], 2)
        self.assertTrue(all("duration_s" not in s for s in normalized["steps"] if s["kind"].startswith("fill")))
        self.assertEqual(json.loads(c.program_catalog("device", [p])[0])["programs"][0], normalized)
        p["steps"][0]["duration_s"] = 15
        with self.assertRaises(ValueError): c.recipe(p)
        for bad in (True, 3, "2"):
            p["schema"] = bad
            with self.assertRaises(ValueError): c.recipe(p)

    def test_catalog_more_than_three_and_authoritative_empty(self):
        programs=[dict(program(),id=f"program_{i}") for i in range(8)]
        body, digest=c.program_catalog("device_fixture",programs)
        data=json.loads(body)
        self.assertEqual(data["count"],8)
        self.assertTrue(data["complete"])
        self.assertEqual(c.program_catalog("device_fixture",list(reversed(programs))),(body,digest))
        body, empty_digest=c.program_catalog("device_fixture",[])
        self.assertEqual(json.loads(body)["programs"],[])
        self.assertNotEqual(digest,empty_digest)
        with self.assertRaises(ValueError): c.program_catalog("device_fixture",[program(),program()])

    def test_catalog_rejects_invalid_and_oversized_whole_snapshot(self):
        invalid=program(); invalid["steps"]=[{"kind":"invalid"}]
        with self.assertRaises(ValueError): c.program_catalog("device_fixture",[program(),invalid])
        with self.assertRaises(ValueError): c.program_catalog("device_fixture",[dict(program(),id=f"program_{i}") for i in range(100)])
        with self.assertRaises(ValueError): c.program_catalog("device_fixture",[dict(program(),id=f"program_{i}") for i in range(c.MAX_PROGRAMS+1)])

    def test_cycles_derive_duration(self):
        p=program(); p["steps"][2].update(cycles=10,reverse_s=3)
        normalized=c.recipe(p)
        self.assertEqual(normalized["steps"][3]["duration_s"],60)
        self.assertEqual(c.recipe(normalized),normalized)
        for bad in (-1,True,1.5,1801):
            p["steps"][2]["cycles"]=bad
            with self.assertRaises(ValueError): c.recipe(p)
        p=program(); p["steps"][1]["cycles"]=1
        with self.assertRaises(ValueError): c.recipe(p)

    def test_original_spindle_speed_defaults(self):
        self.assertEqual(c.washer_speed_default("wash"), 1)
        self.assertEqual(c.washer_speed_default("dry"), 10)
        for kind in ("home", "fill_a", "fill_b", "drain", "wait", None):
            self.assertEqual(c.washer_speed_default(kind), 0)

    def test_valid_program_and_digest(self):
        p = c.recipe(program())
        self.assertEqual(p["steps"][0]["kind"], "home")
        self.assertEqual([s["kind"] for s in p["steps"][1:]],
                         ["fill_a","wait","wash","drain","fill_b","wash","drain","dry"])
        self.assertEqual(c.recipe(p), p)
        self.assertEqual(c.digest(p), c.digest(json.loads(c.canonical(p))))

    def test_invalid_recipe_order(self):
        only_home=program(); only_home["steps"]=[{"kind":"home","duration_s":10,"rps":0}]
        with self.assertRaises(ValueError): c.recipe(only_home)
        for kinds in [("wash",), ("fill_a", "dry"), ("fill_a", "home"),
                      ("fill_a", "fill_b", "drain")]:
            p = program(); p["steps"] = [{"kind": k, "duration_s": 10, "rps": 1 if k in {"wash", "dry"} else 0} for k in kinds]
            with self.subTest(kinds=kinds), self.assertRaises(ValueError): c.recipe(p)
        p=program(); p["steps"]=[{"kind":k,"duration_s":10,"rps":0} for k in ("fill_a","drain","fill_b","drain")]
        self.assertEqual([s["kind"] for s in c.recipe(p)["steps"]],
                         ["home","fill_a","drain","fill_b","drain"])

    def test_manual_wait_is_not_part_of_active_duration(self):
        p = program()
        p["steps"] = [dict(kind="wait", duration_s=3600, rps=0) for _ in range(6)]
        self.assertEqual(len(c.recipe(p)["steps"]), 7)

    def test_limits_and_nonfinite(self):
        for value in [True, -1, 0, 301, float("nan"), float("inf"), "10", 1.5]:
            p = program(); p["steps"][0]["duration_s"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): c.recipe(p)

    def test_malformed_steps(self):
        for steps in [[], [1, 2], [None, {}], "home", [{}]*33]:
            p = program(); p["steps"] = steps
            with self.subTest(steps=steps), self.assertRaises(ValueError): c.recipe(p)

    def test_target_quarters_and_limits(self):
        payload = {"a":37.25, "rise_window_s":600, "minimum_rise_c":1}
        self.assertEqual(c.command("heater", "set_temperature", payload), payload)
        for value in [0, 9.75, 50.25, 37.1, True, "37", float("nan")]:
            with self.subTest(value=value), self.assertRaises(ValueError): c.command("heater", "set_temperature", dict(payload, a=value))

    def test_heater_protection_cannot_be_missing_or_disabled(self):
        with self.assertRaises(ValueError): c.command("heater", "set_temperature", {"a":37})
        with self.assertRaises(ValueError): c.targets({"a":37,"b":37})
        for key, values in {"rise_window_s":[0,29,3601,True], "minimum_rise_c":[0,0.1,6,float("nan")]}.items():
            for invalid in values:
                p={"a":37,"rise_window_s":600,"minimum_rise_c":1,key:invalid}
                with self.subTest(key=key,invalid=invalid), self.assertRaises(ValueError): c.command("heater","set_temperature",p)

    def test_washer_recipe_has_no_temperature_control(self):
        p=program(); p.update(temperature_min=100,temperature_max=-100)
        self.assertNotIn("temperature_min",c.recipe(p))
        self.assertNotIn("temperature_max",c.recipe(p))

    def test_remote_start_and_wrong_device_are_rejected(self):
        for kind, name in [("washer", "start"), ("heater", "start"), ("heater", "enable_heating"),
                           ("heater", "load_recipe"), ("washer", "set_temperature")]:
            with self.assertRaises(ValueError): c.command(kind, name, {})

    def test_ota_cannot_supply_arbitrary_url(self):
        for release in ["../other", "https://attacker.invalid/x", "x\n", ""]:
            with self.assertRaises(ValueError): c.command("washer", "ota", {"release": release})

    def test_heater_event_quality(self):
        value = {"protocol":1, "event_id":"evt", "boot_id":"boot", "seq":1, "uptime_ms":42, "sampled_at":0,
                 "status":{"state":"idle", "firmware":"3.2.0-rc1", "hardware":c.HEATER_HARDWARE,
                           "control_interface":"heater-control-v1","local_enable":True,"remote_start":False,
                           "a":{"valid":True,"temperature":37,"target":37,"fault":"none","output":False}}}
        self.assertEqual(c.event(value,"heater"), value)
        value["status"]["control_method"] = "pi_fixed"
        value["status"]["a"]["power_percent"] = 20
        self.assertEqual(c.event(value,"heater"), value)
        for invalid in [True, -127, float("nan"), 100]:
            bad=copy.deepcopy(value); bad["status"]["a"]["temperature"]=invalid
            with self.assertRaises(ValueError): c.event(bad,"heater")
        value["status"]["a"]["valid"] = False
        value["status"]["a"].pop("temperature")
        c.event(value, "heater")

    def test_heater_interface_requires_local_start(self):
        value = {"protocol":1, "event_id":"evt", "boot_id":"boot", "seq":1, "uptime_ms":42, "sampled_at":0,
                 "status":{"state":"idle", "firmware":"3.2.0-rc1", "hardware":c.HEATER_HARDWARE,
                           "control_interface":"heater-control-v1","local_enable":True,"remote_start":False,
                           "a":{"valid":False,"target":37,"fault":"none","output":False}}}
        for change in ({"control_interface":"legacy"},{"local_enable":False},{"remote_start":True}):
            bad=copy.deepcopy(value); bad["status"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): c.event(bad,"heater")

    def test_withdrawn_heater_hardware_is_rejected(self):
        value = {"protocol":1,"event_id":"evt","boot_id":"boot","seq":1,"uptime_ms":0,"sampled_at":0,
                 "status":{"state":"idle","firmware":"old","hardware":"heater-esp8266-v2"}}
        with self.assertRaises(ValueError): c.event(value,"heater")

    def test_observation_flag_is_not_truthy_string(self):
        with self.assertRaises(ValueError):
            c.event({"protocol":1, "event_id":"evt", "boot_id":"boot", "seq":1, "uptime_ms":0,
                     "sampled_at":0,"status":{},"observation":"false"}, "heater")
