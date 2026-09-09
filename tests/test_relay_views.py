"""Protect the relay identity details in the native list and card views."""
from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRelayLocationDetailViews(TransactionCase):
    def _view_arch(self, xmlid, view_type):
        view = self.env.ref("iot_control_center." + xmlid)
        result = self.env["iot.device"].get_view(view.id, view_type)
        return etree.fromstring(result["arch"])

    def test_list_always_shows_detail_next_to_name(self):
        arch = self._view_arch("view_iot_device_tree", "list")
        details = arch.xpath("./field[@name='location_detail']")
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].getprevious().get("name"), "name")
        self.assertIsNone(details[0].get("optional"))
        self.assertIsNone(details[0].get("column_invisible"))
        self.assertIsNone(details[0].get("invisible"))

    def test_card_loads_and_displays_detail_without_a_label(self):
        arch = self._view_arch("view_iot_device_kanban", "kanban")
        self.assertEqual(len(arch.xpath("./field[@name='location_detail']")), 1)
        details = arch.xpath(".//t[@t-name='card']//div[@class='iot_relay_location_detail']")
        self.assertEqual(len(details), 1)
        detail = details[0]
        self.assertIsNone(detail.get("t-if"))
        self.assertEqual(detail.get("t-att-title"), "record.location_detail.value || ''")
        self.assertEqual(len(detail.xpath("./field[@name='location_detail']")), 1)
        self.assertFalse("".join(detail.itertext()).strip())
        self.assertFalse(detail.xpath(".//label | .//*[@t-raw]"))
        self.assertIn("iot_device_identity", detail.getprevious().get("class"))

    def test_card_keeps_room_slot_and_full_label_tooltips(self):
        arch = self._view_arch("view_iot_device_kanban", "kanban")
        detail = arch.xpath(".//t[@t-name='card']//div[@class='iot_relay_location_detail']")[0]
        location = detail.getnext()
        self.assertIn("iot_relay_location", location.get("class").split())
        self.assertIsNone(location.get("t-if"))
        self.assertEqual(location.get("t-att-title"), "record.location_id.value || ''")
        self.assertEqual(len(location.xpath("./field[@name='location_id']")), 1)
        self.assertEqual(len(location.getnext().xpath("./field[@name='switch_id_display']")), 1)
        heading = detail.getprevious().find("h3")
        self.assertEqual(heading.get("t-att-title"), "record.name.value")
