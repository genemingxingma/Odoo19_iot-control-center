"""Keep filesystem mounting aligned with the actual ESP32 partition table."""
import csv
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]/'firmware/instruments'

class WasherBuildContract(unittest.TestCase):
    def test_retained_ui_recovers_after_screen_restart_without_auto_resume(self):
        source=(ROOT/'src/washer.cpp').read_text()
        boot=source.split('if (!strcmp(command, "UI|BOOT|4")) {',1)[1].split('if (!strcmp(command, "UI|HELLO|4"))',1)[0]
        self.assertIn('stopRun(Storage, "Operator screen restarted")',boot)
        self.assertIn('display.invalidate()',boot)
        self.assertNotIn('startRun()',boot)
        self.assertIn('prints "UI|BOOT|4",0',(ROOT/'hmi/page-init-refresh-candidate.txt').read_text())
        self.assertIn('prints "UI|HELLO|4",0',(ROOT/'hmi/heartbeat.txt').read_text())

    def test_controller_can_pair_with_an_already_booted_v4_screen(self):
        source=(ROOT/'src/washer.cpp').read_text()
        hello=source.split('if (!strcmp(command, "UI|HELLO|4")) {',1)[1].split(
            '// STOP remains',1)[0]
        self.assertIn('millis() > 30000 || washer.running || startup.active()',hello)
        self.assertIn('nativeScreenConfirmed = true;',hello)
        self.assertIn('screenReady = true;',hello)

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
        self.assertIn('idleForSettings() && display.page!=1 && display.page<6',source)
        self.assertIn('!idleForSettings() || display.page==1 || display.page>=6',source)
        self.assertIn('if (display.page==1) pendingCatalog=*text;',source)
        self.assertIn('candidate.find(programLibrary.items[librarySelection].id)',source)

    def test_operator_ui_omits_hardware_prose(self):
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertNotIn('(read only)',source)
        ui=(ROOT/'include/tjc_ui.hpp').read_text()
        for label in ('Open rotor', 'Lid open', 'Lid closed', 'no PSRAM', 'OFFLINE READY'):
            self.assertNotIn(label,ui)
        self.assertNotIn('Keep hands clear and check the drain tubing.',ui)
        self.assertIn('Choose a program, then review before starting.',ui)
        self.assertIn('Header = rgb565(15, 67, 122)',ui)
        self.assertIn('Button = rgb565(216, 233, 250)',ui)
        self.assertIn('constexpr uint8_t Font = 1',ui)
        self.assertNotIn('fill(',ui)
        self.assertNotIn('xstr ',ui)
        self.assertIn('page page',ui)

    def test_native_program_selector_supports_the_full_local_catalog(self):
        source=(ROOT/'src/washer.cpp').read_text()
        ui=(ROOT/'include/tjc_ui.hpp').read_text()
        self.assertIn('librarySelection = (librarySelection + 1) % programLibrary.count',source)
        self.assertIn('librarySelection ? librarySelection - 1 : programLibrary.count - 1',source)
        self.assertIn('view.programCount=programLibrary.count',source)
        self.assertIn('Program " + String(view.selectedProgram + 1)',ui)

    def test_completed_run_requires_explicit_home_acknowledgement(self):
        source=(ROOT/'src/washer.cpp').read_text()
        home=source.split('if (!strcmp(command, "UI|HOME")) {',1)[1].split(
            '} else if (!strcmp(command, "UI|SETTINGS"))',1)[0]
        self.assertIn('washer.completed = false;',home)
        self.assertIn('display.page = tjc::Overview;',home)

    def test_sd_update_back_returns_to_maintenance(self):
        source=(ROOT/'src/washer.cpp').read_text()
        back=source.split('} else if (!strcmp(command, "UI|BACK")',1)[1].split(
            'display.dirty = true;',1)[0]
        self.assertIn('if (display.page == tjc::SdConfirm)',back)
        self.assertIn('display.page = tjc::Maintenance;',back)

    def test_loading_button_cannot_bypass_machine_state_guards(self):
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertIn('!washer.running || !washer.waiting || loading.active',source)
        self.assertIn('if (loadingCalibrated) nextLoadingPosition();',source)
        self.assertIn('else saveLoadingReference();',source)

    def test_pump_review_keeps_actionable_start_errors(self):
        source=(ROOT/'src/washer.cpp').read_text()
        self.assertIn('view.notice = uiMessage.length() ? uiMessage : !view.ready ? view.notice : pumpReady ?',source)
        self.assertIn('Automatic startup preparation is not complete.',source)
        self.assertIn('Set Buffer A and B fill times in Settings.',source)

    def test_startup_preparation_has_no_lock_or_manual_prepare_action(self):
        source=(ROOT/'src/washer.cpp').read_text()
        setup=(ROOT/'lib/InstrumentCore/src/washer_setup.hpp').read_text()
        self.assertNotIn('locallyArmed',setup)
        self.assertNotIn('confirmInitialization',setup)
        self.assertNotIn('UI|PREPARE_CONFIRM',source)
        self.assertNotIn('UI|PREPARE\"',source)
        self.assertNotIn('Prepare Machine',source)
        self.assertNotIn('Tap INITIALIZE',source)
        self.assertIn('startup.readyToStart(',source)
        self.assertNotIn('startupAwaitAt',source)
        self.assertIn('if (view.startup) return StartupPage;', (ROOT/'include/tjc_ui.hpp').read_text())

    def test_compiled_screen_omits_obsolete_prepare_actions(self):
        tft = ROOT/'hmi/washer-native-v4.tft'
        self.assertTrue(tft.is_file())
        image = tft.read_bytes()
        self.assertNotIn(b'UI|PREPARE', image)
        self.assertNotIn(b'Prepare Machine', image)
        for action in (b'UI|BACK', b'UI|HOME', b'UI|WIFI_CANCEL',
                       b'UI|PUMP_CANCEL', b'UI|STOP'):
            self.assertIn(action, image)
        self.assertEqual(len(image), 1753064)

    def test_heater_control_interface_is_local_start_only(self):
        source=(ROOT/'src/heater.cpp').read_text()
        self.assertIn('CONTROL_INTERFACE = "heater-control-v1"',source)
        self.assertIn('s["local_enable"] = true; s["remote_start"] = false;',source)
        self.assertIn('void usbDiagnostics()',source)
        self.assertIn('usbDiagnostics();',source)
        self.assertIn('d["detected_sensor_count"] = detectedSensorCount;',source)
        self.assertIn('d["detected_sensor_rom"] = addressText(detectedSensorAddress);',source)
        self.assertNotIn('name == "start"',source)
        self.assertNotIn('name == "enable_heating"',source)

    def test_instruments_report_operator_visible_device_ids(self):
        heater=(ROOT/'src/heater.cpp').read_text()
        washer=(ROOT/'src/washer.cpp').read_text()
        runtime=(ROOT/'include/runtime.hpp').read_text()
        self.assertIn('deviceIdentity("HTR")',heater)
        self.assertIn('deviceIdentity("WSH")',washer)
        self.assertIn('s["device_id"] = deviceId;',heater)
        self.assertIn('s["device_id"] = deviceId;',washer)
        self.assertIn('/iot_control_center/instrument/discover',runtime)
        self.assertIn('binding_required',runtime)

    def test_heater_oled_prioritizes_large_readable_content(self):
        ui=(ROOT/'lib/InstrumentCore/src/heater_panel.hpp').read_text()
        self.assertIn('d.setTextSize(4); d.setCursor(0, 13); d.print(v.temperature);',ui)
        self.assertIn('d.setTextSize(2); d.setCursor(0, 3); d.print("ALARM");',ui)
        self.assertNotIn('1:ID  2:HEAT  3:SET',ui)

if __name__=='__main__': unittest.main()
