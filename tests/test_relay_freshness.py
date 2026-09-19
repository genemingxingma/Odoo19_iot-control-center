import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRelayFreshness(TransactionCase):
    def setUp(self):
        super().setUp()
        self.device = self.env["iot.device"].create({"name": "Freshness fixture", "serial": "FRESHNESS-TEST"})
        self.now = fields.Datetime.now()

    def report(self, at, **overrides):
        payload = dict(module_id=self.device.serial, state="off", firmware_version="2.0.2",
                       delay_active=False, delay_remaining_sec=0, manual_override=False,
                       schedule_version=4, schedule_count=14, time_synced=True,
                       control_inhibit=True, safety_trip=False, ota_state="idle")
        payload.update(overrides)
        message = self.env["iot.mqtt.message"]._create_from_mqtt(
            "iot/relay/FRESHNESS-TEST/telemetry", json.dumps(payload), received_at=at)
        message._process_one()
        return message

    def test_whole_late_report_is_inert_and_preserved(self):
        self.report(self.now)
        with patch.object(type(self.device), "_sync_network_config") as network:
            late = self.report(self.now - timedelta(hours=2), state="on", firmware_version="1.8.8",
                               delay_active=True, delay_remaining_sec=900, schedule_version=3,
                               control_inhibit=False, manual_override=True, ota_state="failed")
            network.assert_not_called()
        self.assertEqual(late.state, "done")
        self.assertEqual(late.device_id, self.device)
        self.assertEqual(self.device.last_seen, self.now)
        self.assertEqual(self.device.relay_state, "off")
        self.assertEqual(self.device.firmware_version, "2.0.2")
        self.assertFalse(self.device.delay_active)
        self.assertFalse(self.device.manual_override)
        self.assertEqual(self.device.schedule_applied_version, 4)
        self.assertEqual(self.device.schedule_last_sync_at, self.now)
        self.assertEqual(self.device.schedule_execution_state, "blocked")

    def test_late_report_without_state_cannot_move_contact_backwards(self):
        self.report(self.now)
        self.report(self.now - timedelta(minutes=30), state=None)
        self.assertEqual(self.device.last_seen, self.now)

    def test_direct_auxiliary_reports_do_not_regress(self):
        self.report(self.now)
        at = self.now - timedelta(minutes=1)
        self.device._apply_delay_report({"delay_active": True}, at)
        self.device._apply_manual_override_report({"manual_override": True}, at)
        self.device._apply_identity_report("WRONG-ID", at)
        self.device._apply_firmware_report("1.8.8", at)
        self.device._apply_runtime_report({"mqtt_route": "fallback"}, at)
        self.device._apply_firmware_upgrade_feedback("failed", reported_at=at)
        self.device._apply_schedule_report({"schedule_version": 3}, at)
        self.assertEqual(self.device.last_seen, self.now)
        self.assertEqual(self.device.module_id, self.device.serial)
        self.assertEqual(self.device.firmware_version, "2.0.2")
        self.assertFalse(self.device.delay_active)
        self.assertFalse(self.device.manual_override)
        self.assertNotEqual(self.device.firmware_upgrade_state, "failed")

    def test_schedule_sync_does_not_imply_permission_to_start(self):
        self.device.write({"schedule_version": 4, "schedule_dirty": False})
        self.report(self.now)
        self.assertEqual(self.device.schedule_sync_state, "in_sync")
        self.assertEqual(self.device.schedule_execution_state, "blocked")
        self.report(self.now + timedelta(seconds=1), safety_trip=True)
        self.assertEqual(self.device.schedule_execution_state, "tripped")
        self.report(self.now + timedelta(seconds=2), control_inhibit=False, time_synced=False)
        self.assertEqual(self.device.schedule_execution_state, "clock")
        self.report(self.now + timedelta(seconds=3), control_inhibit=False, schedule_count=0)
        self.assertEqual(self.device.schedule_execution_state, "empty")
        self.report(self.now + timedelta(seconds=4), control_inhibit=False)
        self.assertEqual(self.device.schedule_execution_state, "ready")

    def test_missing_or_invalid_flags_are_not_reported_as_safe(self):
        self.assertEqual(self.device.schedule_execution_state, "unknown")
        self.report(self.now, time_synced=None)
        self.assertEqual(self.device.schedule_execution_state, "unknown")
        self.report(self.now, control_inhibit="false")
        self.assertEqual(self.device.schedule_execution_state, "unknown")
        self.report(self.now)
        self.device.runtime_reported_at = self.now - timedelta(minutes=10)
        self.assertEqual(self.device.schedule_execution_state, "stale")

    def test_many_reverse_order_reports_leave_newest_state(self):
        self.report(self.now, state="off")
        for minute in (2, 5, 1, 30, 10):
            self.report(self.now - timedelta(minutes=minute), state="on")
        self.assertEqual(self.device.last_seen, self.now)
        self.assertEqual(self.device.relay_state, "off")
