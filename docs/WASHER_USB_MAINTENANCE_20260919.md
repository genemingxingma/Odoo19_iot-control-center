# Washer USB maintenance: transport validation

## Status and decision

The user accepts one future update method for both devices. Prefer the existing
external USB connection: the ESP32 is directly accessible through the CH340,
and a temporary RAM bridge can reach the internally connected TJC screen.
No screen disassembly or additional USB-to-TTL adapter was needed for this test.

**Validated: communication, not a completed firmware upgrade.** Neither the
ESP32 application nor the screen TFT was flashed in this session. Wi-Fi
credentials were not read, logged or changed. Production Odoo was not changed.

## Hardware evidence, 2026-09-19

- USB serial device: CH340, COM4 at the time of testing.
- Main controller: classic ESP32-D0WD-V3, revision 3.1, 4MB flash.
- Screen identity returned through the bridge: TJC8048X550_011C.
- Screen UART: ESP32 UART2, RX16 / TX17, 115200 baud, 8N1.
- Operator confirmed the screen was lit and motor/pump power disconnected.
- 16 exact echo round trips passed, 4,064 payload bytes checked.
- A single 4,005-byte command burst returned all 3,795 expected payload bytes,
  without truncation, duplication or reordering.
- ESP32 returned to ROM download mode after the probe, not the old application.
- A subsequent esptool verification of all 4,194,304 flash bytes matched the
  private pre-upgrade backup. Backup contents and device identity receipts are
  intentionally excluded from Git.

## Implementation

`firmware/instruments/maintenance/usb_screen_bridge.c` and its assembly/linker
files implement a RAM-only bridge. They contain no flash-writing, network,
normal washer application, pump-start or motion logic. Known output pins are
held low. UART overflow, framing and parity errors halt the bridge rather than
continue forwarding a potentially corrupt firmware stream. There is no
automatic reboot into the washer application.

`tools/build_washer_usb_bridge.ps1` builds the bridge separately from the normal
PlatformIO firmware. Output is under the ignored `out/maintenance` directory.

`tools/probe_washer_usb_screen.py` validates the ELF and exported RAM segments,
checks the ESP32 identity before RAM upload, reads the screen model, performs
echo tests, and resets the controller back into ROM download mode. Its CLI does
not expose a TFT upload or arbitrary screen-command option. It requires the
operator to confirm actuator power isolation and supply the expected MAC.

The early register-by-register diagnostic is not the transfer implementation.
It lost reply bytes and must not be reused for firmware transfer. The RAM bridge
uses the ESP-IDF UART FIFO access/accounting conventions instead.

## Repeating the diagnostic

Keep the screen and controller powered, with motor/pump supplies isolated.
Do not run this against an operating instrument. Find and verify the USB port
and the expected device identity first; do not assume COM4 on another computer.

```powershell
./tools/build_washer_usb_bridge.ps1
& deploy/artifacts/instrument-venv/Scripts/python.exe tools/probe_washer_usb_screen.py `
  --port <verified-port> --expected-mac <verified-device-mac> `
  --confirm-actuator-power-off `
  --receipt deploy/artifacts/washer-usb-screen-bridge-probe.json
```

Do not open a serial monitor concurrently. The bridge's fixed 115200 baud must
not be changed by an automatic baud-scanning screen-download tool.

## What remains before a full USB release

1. Implement and validate the TFT download handshake, per-block confirmation,
   timeout/failure handling, correct-model rejection and post-update UI checks.
   Echo success alone does not exercise screen-flash writing or its bootloader.
2. Finalize the matched ESP32 release and commissioning files. In particular,
   on-screen Wi-Fi configuration, multiple locally stored program selection,
   and the requested startup/cycle behavior must not be represented as complete
   merely because this maintenance transport works.
3. Rehearse the first ESP32 migration: the old and new partition layouts differ.
   Do not write only the new application at an assumed offset or erase original
   credentials/configuration without an explicit migration plan and backup.
4. Upgrade and verify the matched ESP32/screen pair, with actuator power still
   isolated, before commissioning outputs. A screen-only upgrade while leaving
   an incompatible old main-controller application is not accepted.

The prepared SD directory remains non-autostart. This work does not turn its
candidate files into a validated SD update package. Previously implemented SD
or OTA capabilities are not removed; they are not required for this USB test.

## Checks

- Bridge compiled with `-Wall -Wextra -Werror`; no unresolved external symbols.
- Loadable sections: 968 bytes of IRAM and 61 bytes of DRAM, no flash segments.
- Bridge text SHA-256:
  `03a4ad64ac67cbb3478990999bb4ced0d7f0a42b121cc158614d4a25066b1326`.
- Bridge data SHA-256:
  `23408544d1919af7c7558e2b33058f9a657ea3ebbe126224e2fd72bb7a22e491`.
- `core_tests/test_washer_usb_bridge.py`: 13 tests passed.
- Existing native instrument checks: 524 passed; UI checks: 65 passed;
  heater-panel tests passed. These tests are not physical commissioning.

## Primary references

- Espressif RAM loading and its IRAM/DRAM-only restriction:
  https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/advanced-commands.html
- Espressif ROM RAM-download command sequence:
  https://docs.espressif.com/projects/esptool/en/release-v4/esp32/advanced-topics/serial-protocol.html
- Local Arduino-ESP32 SDK `hal/esp32/include/hal/uart_ll.h` and
  `soc/esp32/include/soc/uart_reg.h`: APB FIFO reads, AHB writes, FIFO pointers.
- TJC command reference (`prints` is used without changing screen UI/settings):
  https://wiki.tjc1688.com/commands/index.html

## Update request preflight, 2026-09-19

Following the user's request to start updating, the candidate was rebuilt and
its application, partition-table and TFT hashes still matched the prepared
artifacts. The physical RAM-bridge probe passed again and returned the ESP32 to
ROM. No flash write was performed during this preflight.

`tools/update_washer_usb_screen.py` now implements a separate, opt-in TFT
uploader, with an approved-file SHA-256 check, device/model/capacity checks,
4096-byte blocks with individual acknowledgements, no ambiguous automatic
retries, progress receipts, and a post-upload requirement for two V3 heartbeat
observations. Dry-run does not open the serial port. It must not be executed
until the matched ESP32 application is installed and held in ROM. The tool does
not itself install or verify that application; that remains a separate gate.

Ten additional offline uploader tests passed (23 including the bridge tests),
and the actual TFT passed dry-run artifact validation. This does not validate
the TFT flash-writing operation on the physical screen.

The implementation follows the manufacturer's authored two-page HMI download
protocol, available as a third-party-hosted copy:
https://www.scribd.com/document/1013354348/HMI%E4%B8%8B%E8%BD%BD%E5%8D%8F%E8%AE%AE%E8%AF%B4%E6%98%8E
The existing original controller's `check_update()` uses the same transfer
command but omits acknowledgement handling; it is not reused.

Before changing flash, the user was asked to choose between completing the
missing on-screen Wi-Fi/program-library/startup features first (recommended)
and deliberately installing a non-operational commissioning build. No answer
had been received when this preflight record was written. Neither the screen
nor ESP32 application was upgraded, and operation must not be represented as
accepted. Keep actuator supplies isolated while the controller is in ROM.

## Feature completion candidate, 2026-09-19

The user selected feature completion before flashing and clarified that three
programs is a typical count, not a storage limit. The 3.4.0-rc3 candidate has
touchscreen Wi-Fi entry, a paginated authoritative platform program catalog,
explicit wash-cycle counts, and home-then-drain startup sequencing using the
original motor outputs. See `WASHER_PROGRAM_SYNC_20260919.md` for synchronization
and offline behavior. The catalog is never truncated to three or partly applied.

Native safety checks (526), UI checks (168), heater-panel, washer-setup and shared
catalog-parser tests pass. The ESP32 application compiles. No USB flash was
performed during the initial feature/synchronization changes; the later rc3
application was written and verified over USB. The previously listed
provisioning, paired-update, partition migration and physical commissioning
gates remain in force; these software tests do not clear them.

## Subsequent paired USB flash

Following the user's explicit flash-test request, the ESP32 partition migration
and paired screen upload were completed. See [USB test results](WASHER_USB_TEST_20260919.md)
for exact hashes, runtime evidence, blue/white UI changes and remaining gates.
The earlier no-flash statements above are historical preflight records, not
the current device state. Actuator commissioning remains disabled.
