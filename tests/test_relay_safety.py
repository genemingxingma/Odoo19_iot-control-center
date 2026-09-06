import json
import uuid
import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestRelaySafety(TransactionCase):
    def setUp(self):
        super().setUp()
        thailand = self.env["res.country"].search([("code", "=", "TH")], limit=1)
        self.env.company.partner_id.country_id = thailand
        suffix = uuid.uuid4().hex[:8]
        self.module_id = f"SAFE{suffix}"
        self.device = self.env["iot.device"].create(
            {
                "name": "Safety relay",
                "serial": self.module_id,
                "module_id": self.module_id,
                "company_id": self.env.company.id,
            }
        )

    def test_reported_module_id_wins_over_legacy_topic_alias(self):
        legacy_alias = f"OLD{uuid.uuid4().hex[:8]}"
        message = self.env["iot.mqtt.message"].create(
            {
                "topic": f"iot/relay/{legacy_alias}/telemetry",
                "device_serial": legacy_alias,
                "message_type": "telemetry",
                "payload": json.dumps(
                    {
                        "module_id": self.module_id,
                        "state": "off",
                        "firmware_version": "test",
                    }
                ),
            }
        )

        message._process_one()

        self.assertEqual(message.device_id, self.device)
        self.assertFalse(self.env["iot.device"].search([("serial", "=", legacy_alias)]))

    def test_stale_state_report_cannot_override_newer_state(self):
        now = fields.Datetime.now()
        self.device.write({"relay_state": "off", "last_seen": now})

        self.device._apply_state_report("on", reported_at=now - timedelta(minutes=5))

        self.assertEqual(self.device.relay_state, "off")
        self.assertEqual(self.device.last_seen, now)

    def test_maximum_on_time_is_converted_to_seconds(self):
        self.device.max_continuous_on_minutes = 75
        self.assertEqual(self.device._max_on_seconds(), 4500)

    def test_schedule_uses_company_country_timezone(self):
        self.env["iot.schedule"].create(
            {
                "name": "Bangkok schedule",
                "device_id": self.device.id,
                "command": "on",
                "timezone": "UTC",
                "hour": 2,
                "minute": 0,
            }
        )

        entries = self.device._iter_schedule_entries()

        self.assertTrue(entries)
        self.assertEqual({entry["offset_min"] for entry in entries}, {420})

    def test_openwrt_location_comes_from_company(self):
        template = self.env["iot.openwrt.template"].create(
            {
                "name": "Company location",
                "company_id": self.env.company.id,
                "country_code": "US",
                "timezone_name": "UTC",
            }
        )

        payload = template.to_middleware_payload()

        self.assertEqual(payload["country_code"], "TH")
        self.assertEqual(payload["timezone_name"], "Asia/Bangkok")

    def test_incompatible_relay_firmware_is_rejected(self):
        incompatible_header = bytes([0xE9, 0x02, 0x02, 0x40]) + bytes(32)

        with self.assertRaises(UserError):
            self.env["iot.firmware"].create(
                {
                    "name": "Wrong flash layout",
                    "version": "test",
                    "filename": "wrong.bin",
                    "file": base64.b64encode(incompatible_header),
                    "company_id": self.env.company.id,
                }
            )

    def test_company_internal_endpoints(self):
        self.env.company.write(
            {
                "iot_prefer_internal_network": True,
                "iot_internal_host": "192.168.10.15",
                "iot_internal_odoo_port": 8069,
                "iot_internal_mqtt_port": 1883,
                "iot_internal_ota_port": 8443,
            }
        )

        self.assertEqual(self.env.company.get_iot_internal_odoo_base_url(), "http://192.168.10.15:8069")
        self.assertEqual(self.env.company.get_iot_internal_ota_base_url(), "https://192.168.10.15:8443")
        self.assertEqual(self.env.company.get_iot_internal_mqtt_endpoint(), ("192.168.10.15", 1883))

    def test_internal_network_report_confirms_configuration(self):
        self.env.company.write(
            {
                "iot_prefer_internal_network": True,
                "iot_internal_host": "192.168.10.15",
                "iot_internal_mqtt_port": 1883,
            }
        )
        self.device.write({"firmware_version": "2.0.0", "network_config_dirty": True})

        self.device._apply_runtime_report(
            {
                "hardware_profile": "esp8266-1m-dout-64kfs",
                "flash_real_size": 4194304,
                "free_heap": 40000,
                "mqtt_host": "192.168.10.15",
                "mqtt_route": "primary",
                "config_revision": self.device._network_config_payload()["config_revision"],
            }
        )

        self.assertFalse(self.device.network_config_dirty)
        self.assertEqual(self.device.mqtt_route, "primary")
        self.assertEqual(self.device.firmware_hardware_profile, "esp8266-1m-dout-64kfs")
