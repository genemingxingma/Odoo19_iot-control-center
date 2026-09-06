import uuid
from datetime import timedelta
from unittest.mock import patch
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

@tagged("post_install", "-at_install")
class TestV2Contracts(TransactionCase):
    def setUp(self):
        super().setUp()
        self.suffix = uuid.uuid4().hex[:8]
        self.gateway = self.env["iot.th.gateway"].create({"name": "V2", "serial": self.suffix, "company_id": self.env.company.id})
        self.sensor = self.env["iot.th.sensor"].create({"name": "V2 probe", "gateway_id": self.gateway.id,
            "company_id": self.env.company.id, "node_id": "COLLISION", "probe_code": "CH01"})

    def test_event_claim_is_idempotent_and_rejects_identity_reuse(self):
        model = self.env["iot.ingest.event"]
        event_id = uuid.uuid4().hex
        self.assertTrue(model._claim(event_id, "th", "digest", fields.Datetime.now()))
        self.assertFalse(model._claim(event_id, "th", "digest", fields.Datetime.now()))
        with self.assertRaises(ValueError):
            model._claim(event_id, "th", "different", fields.Datetime.now())

    def test_probe_identity_scoped_to_gateway(self):
        other = self.env["iot.th.gateway"].create({"name": "V2 other", "serial": "other" + self.suffix, "company_id": self.env.company.id})
        probe = self.env["iot.th.sensor"].create({"name": "Other", "gateway_id": other.id, "company_id": self.env.company.id,
            "node_id": "COLLISION", "probe_code": "CH01"})
        self.assertNotEqual(probe.id, self.sensor.id)
        with self.assertRaises(ValidationError):
            self.sensor.gateway_id = other

    def test_history_snapshot_survives_location_change_and_is_immutable(self):
        self.sensor.location_detail = "At collection"
        row = self.env["iot.th.reading"].create({"sensor_id": self.sensor.id, "gateway_id": self.gateway.id,
            "temperature": 10, "humidity": 55, "reported_at": fields.Datetime.now()})
        self.sensor.location_detail = "New location"
        self.assertEqual(row.sensor_location_detail, "At collection")
        with self.assertRaises(AccessError):
            row.temperature = 90

    def test_legacy_and_modern_aggregation_agree(self):
        self.env["iot.th.reading"].create([{"sensor_id": self.sensor.id, "gateway_id": self.gateway.id,
            "temperature": t, "humidity": 55, "reported_at": fields.Datetime.now()} for t in [10, 10, 40]])
        model = self.env["iot.th.reading"]
        domain = [("sensor_id", "=", self.sensor.id)]
        self.assertAlmostEqual(model._read_group(domain, [], ["temperature:avg"])[0][0], 20)
        self.assertAlmostEqual(model.read_group(domain, ["temperature:avg"], [])[0]["temperature"], 20)

    def test_command_is_queued_before_publication_and_off_supersedes_on(self):
        device = self.env["iot.device"].create({"name": "V2 relay", "serial": self.suffix, "company_id": self.env.company.id})
        device.action_turn_on()
        device.write({"delay_active": True})
        device.action_turn_off()
        commands = self.env["iot.command"].search([("device_id", "=", device.id), ("command", "=", "relay")], order="id")
        self.assertEqual(commands.mapped("state"), ["cancelled", "queued"])
        self.assertEqual(commands[-1].payload["state"], "off")
        self.assertEqual(commands[-1].payload["command_id"], commands[-1].command_id)

    def test_readonly_user_cannot_control_device(self):
        user = new_test_user(self.env, login="iotread" + self.suffix,
                            groups="base.group_user,iot_control_center.group_iot_user")
        device = self.env["iot.device"].create({"name": "V2 relay", "serial": self.suffix, "company_id": user.company_id.id})
        with self.assertRaises(AccessError):
            device.with_user(user).action_delay_toggle()

    def test_same_host_without_revision_does_not_confirm_network_config(self):
        device = self.env["iot.device"].create({"name": "V2 relay", "serial": self.suffix,
            "firmware_version": "2.0.0", "company_id": self.env.company.id})
        self.env["ir.config_parameter"].sudo().set_param("iot_control_center.mqtt_host", "example.invalid")
        device._apply_runtime_report({"mqtt_host": "example.invalid", "mqtt_route": "primary"})
        self.assertTrue(device.network_config_dirty)
        device._apply_runtime_report({"mqtt_host": "example.invalid", "mqtt_route": "primary",
                                     "config_revision": device._network_config_payload()["config_revision"]})
        self.assertFalse(device.network_config_dirty)

    def test_operator_cannot_control_another_company(self):
        user = new_test_user(self.env, login="iotoperate" + self.suffix,
                            groups="base.group_user,iot_control_center.group_iot_operator")
        company = self.env["res.company"].create({"name": "Other " + self.suffix})
        device = self.env["iot.device"].create({"name": "Other relay", "serial": self.suffix, "company_id": company.id})
        with self.assertRaises(AccessError):
            device.with_user(user).action_turn_off()

    def test_missing_safety_limit_blocks_on_but_not_timer_cancel(self):
        device = self.env["iot.device"].create({"name": "UV fixture", "serial": self.suffix,
            "company_id": self.env.company.id, "safety_critical": True, "max_continuous_on_minutes": 0})
        with self.assertRaises(ValidationError):
            device.action_turn_on()
        device.delay_active = True
        device.action_delay_toggle()
        command = self.env["iot.command"].search([("device_id", "=", device.id)], limit=1)
        self.assertEqual(command.command, "delay_cancel")
        self.assertEqual(device.desired_relay_state, "off")

    def test_unconfirmed_delivery_expires_and_exact_late_ack_is_recorded(self):
        device = self.env["iot.device"].create({"name": "Relay", "serial": self.suffix, "company_id": self.env.company.id})
        device.action_turn_off()
        command = self.env["iot.command"].search([("device_id", "=", device.id)], limit=1)
        command.write({"state": "sent", "expires_at": fields.Datetime.now() - timedelta(seconds=1)})
        with patch.object(type(device), "_publish_command_via_middleware", return_value=False):
            self.env["iot.command"]._cron_dispatch()
        self.assertEqual(command.state, "expired")
        device._apply_command_ack({"last_command_id": "wrong", "state": "off"})
        self.assertEqual(command.state, "expired")
        device._apply_command_ack({"last_command_id": command.command_id, "state": "off"})
        self.assertEqual(command.state, "confirmed")

    def test_config_ack_requires_matching_revision(self):
        device = self.env["iot.device"].create({"name": "Relay", "serial": self.suffix, "company_id": self.env.company.id})
        command = self.env["iot.command"]._enqueue(device, "network_set", {"config_revision": "new"})
        command.state = "sent"
        device._apply_command_ack({"last_command_id": command.command_id, "config_revision": "old"})
        self.assertEqual(command.state, "sent")
        device._apply_command_ack({"last_command_id": command.command_id, "config_revision": "new"})
        self.assertEqual(command.state, "confirmed")

    def test_retention_is_explicit_and_respects_probe_exemption(self):
        row = self.env["iot.th.reading"].create({"sensor_id": self.sensor.id, "gateway_id": self.gateway.id,
            "temperature": 10, "humidity": 55, "reported_at": fields.Datetime.now() - timedelta(days=10)})
        self.env.company.iot_history_retention_days = 0
        self.env["iot.th.reading"]._cron_purge_expired_readings()
        self.assertTrue(row.exists())
        self.env.company.iot_history_retention_days = 1
        self.sensor.keep_full_history = True
        self.env["iot.th.reading"]._cron_purge_expired_readings()
        self.assertTrue(row.exists())
        self.sensor.keep_full_history = False
        self.env["iot.th.reading"]._cron_purge_expired_readings()
        self.assertFalse(row.exists())
