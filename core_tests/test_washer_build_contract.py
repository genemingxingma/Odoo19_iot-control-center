"""Keep filesystem mounting aligned with the actual ESP32 partition table."""
import csv
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]/'firmware/instruments'

class WasherBuildContract(unittest.TestCase):
    def test_filesystem_mount_uses_declared_label_without_auto_format(self):
        lines=[line for line in (ROOT/'partitions_4mb.csv').read_text().splitlines()
               if line.strip() and not line.startswith('#')]
        rows=[[cell.strip() for cell in row] for row in csv.reader(lines)]
        partition=next(row for row in rows if row[0]=='littlefs')
        self.assertEqual(partition[1:5],['data','spiffs','0x370000','0x90000'])
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertRegex(source,r'LittleFS\.begin\(false,\s*"/littlefs",\s*10,\s*"littlefs"\)')
        self.assertNotRegex(source,r'LittleFS\.begin\(true')

    def test_library_page_does_not_block_automatic_sync(self):
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertIn('idleForSettings() && display.page<6',source)
        self.assertIn('!idleForSettings() || display.page>=6',source)
        self.assertIn('candidate.find(programLibrary.items[librarySelection].id)',source)

    def test_operator_ui_omits_hardware_prose(self):
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertNotIn('(read only)',source)
        ui=(ROOT/'include/tjc_ui.hpp').read_text()
        for label in ('Open rotor', 'Lid open', 'Lid closed', 'no PSRAM', 'OFFLINE READY'):
            self.assertNotIn(label,ui)
        self.assertIn('Check program and liquid. Keep hands clear; confirm start.',ui)
        self.assertIn('Header = rgb565(15, 67, 122)',ui)
        self.assertIn('Button = rgb565(216, 233, 250)',ui)

    def test_heater_control_interface_is_local_start_only(self):
        source=(ROOT/'src/heater.cpp').read_text()
        self.assertIn('CONTROL_INTERFACE = "heater-control-v1"',source)
        self.assertIn('s["local_enable"] = true; s["remote_start"] = false;',source)
        self.assertIn('void usbDiagnostics()',source)
        self.assertIn('usbDiagnostics();',source)
        self.assertNotIn('name == "start"',source)
        self.assertNotIn('name == "enable_heating"',source)

if __name__=='__main__': unittest.main()
