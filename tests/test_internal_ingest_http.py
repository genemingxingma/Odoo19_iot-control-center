"""Real HTTP dispatch must acknowledge only committed ingestion work."""
import json
import secrets
import time
import uuid

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestInternalIngestHTTP(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = secrets.token_hex(32)
        cls.env["ir.config_parameter"].sudo().set_param("iot_control_center.middleware_token", cls.token)

    def event(self, **values):
        return {"protocol_version": 2, "event_id": uuid.uuid4().hex,
                "received_at_ms": int(time.time() * 1000), **values}

    def post_event(self, endpoint, event, token=None):
        return self.url_open("/iot_control_center/internal/" + endpoint,
            data=json.dumps(event), headers={"Content-Type": "application/json",
                "X-IoT-Middleware-Token": self.token if token is None else token})

    def test_mqtt_http_persists_once_and_rejects_changed_replay(self):
        topic = "iot/relay/HTTP" + uuid.uuid4().hex + "/telemetry"
        event = self.event(topic=topic, payload=json.dumps({"state": "off"}))
        first = self.post_event("mqtt_ingest", event)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["ok"])
        replay = self.post_event("mqtt_ingest", event)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["duplicate"])
        changed = self.post_event("mqtt_ingest", {**event, "payload": json.dumps({"state": "on"})})
        self.assertEqual(changed.status_code, 400)
        self.env.invalidate_all()
        self.assertEqual(self.env["iot.mqtt.message"].search_count([("topic", "=", topic)]), 1)
        self.assertEqual(self.env["iot.ingest.event"].search_count([("event_id", "=", event["event_id"])]), 1)

    def test_failed_mqtt_validation_rolls_back_receipt(self):
        event = self.event(topic=42, payload="invalid topic")
        response = self.post_event("mqtt_ingest", event)
        self.assertEqual(response.status_code, 400)
        self.env.invalidate_all()
        self.assertFalse(self.env["iot.ingest.event"].search_count([("event_id", "=", event["event_id"])]))

    def test_invalid_authentication_does_not_create_receipt(self):
        event = self.event(topic="iot/relay/TEST/status", payload="{}")
        response = self.post_event("mqtt_ingest", event, token="not-authorized")
        self.assertEqual(response.status_code, 401)
        self.env.invalidate_all()
        self.assertFalse(self.env["iot.ingest.event"].search_count([("event_id", "=", event["event_id"])]))

    def test_oversized_body_does_not_create_receipt(self):
        event = self.event(topic="iot/relay/TEST/status", payload="x" * (2 * 1024 * 1024))
        response = self.post_event("mqtt_ingest", event)
        self.assertEqual(response.status_code, 400)
        self.env.invalidate_all()
        self.assertFalse(self.env["iot.ingest.event"].search_count([("event_id", "=", event["event_id"])]))

    def test_openwrt_heartbeat_http_persists_and_deduplicates(self):
        ap = self.env["iot.openwrt.ap"].create({"name": "HTTP heartbeat fixture", "host": "192.0.2.21",
            "company_id": self.env.company.id})
        event = self.event(id=ap.id, auth_token=ap.auth_token, ok=True)
        response = self.post_event("openwrt_heartbeat", event)
        self.assertEqual(response.status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(ap.status, "online")
        self.assertTrue(ap.last_heartbeat_at)
        response = self.post_event("openwrt_heartbeat", event)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["duplicate"])
