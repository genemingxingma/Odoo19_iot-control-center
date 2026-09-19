import hashlib
import json
import secrets
import time
import uuid
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestInstrumentHTTP(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = secrets.token_hex(32)
        cls.device = cls.env["iot.instrument"].sudo().create({"name": "HTTP fixture", "kind": "washer",
            "token_hash": hashlib.sha256(cls.token.encode()).hexdigest()})

    def event(self):
        return {"protocol": 1, "event_id": uuid.uuid4().hex, "boot_id": "http-boot", "seq": 1,
            "uptime_ms": 0, "sampled_at": int(time.time()), "status": {"state": "idle", "firmware": "3.0.0-dev"}}

    def post(self, value, token=None):
        return self.url_open("/iot_control_center/instrument/"+self.device.uid+"/exchange",
            data=json.dumps(value), headers={"Content-Type": "application/json", "X-Instrument-Token": self.token if token is None else token})

    def test_authentication_and_bounded_request(self):
        self.assertEqual(self.post(self.event(), "wrong").status_code, 401)
        body = self.event(); body["padding"] = "x"*32768
        self.assertEqual(self.post(body).status_code, 400)

    def test_replay_and_changed_replay(self):
        body = self.event()
        self.assertEqual(self.post(body).status_code, 200)
        self.assertEqual(self.post(body).status_code, 200)
        body["status"]["state"] = "running"
        self.assertEqual(self.post(body).status_code, 400)

    def test_reading_failure_leaves_no_claim(self):
        body = self.event(); body["log"] = {"run_id": []}
        self.assertEqual(self.post(body).status_code, 400)
        body.pop("log")
        self.assertEqual(self.post(body).status_code, 200)

    def test_firmware_requires_device_authentication(self):
        path = "/iot_control_center/instrument/"+self.device.uid+"/release/unknown/binary"
        self.assertEqual(self.url_open(path).status_code, 401)
        self.assertEqual(self.url_open(path, headers={"X-Instrument-Token": self.token}).status_code, 404)

    def test_program_catalog_authentication_and_conditional_snapshot(self):
        path="/iot_control_center/instrument/"+self.device.uid+"/programs"
        self.assertEqual(self.url_open(path).status_code,401)
        headers={"X-Instrument-Token":self.token}
        response=self.url_open(path,headers=headers)
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body["device_uid"],self.device.uid)
        self.assertTrue(body["complete"])
        self.assertEqual(body["count"],len(body["programs"]))
        self.assertEqual(hashlib.sha256(response.content).hexdigest(),response.headers["X-Catalog-SHA256"])
        headers["If-None-Match"]=response.headers["ETag"]
        self.assertEqual(self.url_open(path,headers=headers).status_code,304)

    def test_catalog_failure_is_not_an_empty_success(self):
        path="/iot_control_center/instrument/"+self.device.uid+"/programs"
        with patch.object(type(self.env["iot.instrument"]), "_program_catalog", side_effect=ValueError("invalid snapshot")):
            response=self.url_open(path,headers={"X-Instrument-Token":self.token})
        self.assertEqual(response.status_code,503)
        self.assertFalse(response.json()["ok"])
        self.assertNotIn("programs",response.json())
        self.assertNotIn("X-Catalog-SHA256",response.headers)
