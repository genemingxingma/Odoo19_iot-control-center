# Instrument V3 Candidate Validation - 2026-09-17

Historical baseline for `3.0.0-dev`. The same-day `3.0.1-dev` hardware-clarification
update supersedes its level-input, washer-temperature-interlock and local-editing
assumptions. Current behavior is in `INSTRUMENTS_V3_COMMISSIONING.md`; this record's
binary hashes and test counts refer only to the earlier baseline.
See `INSTRUMENTS_V3_1_VALIDATION_20260917.md` for the updated test evidence.

Status: DEVELOPMENT CANDIDATE, NOT RELEASED. Odoo module `19.0.2.1.0`,
MCU version `3.0.0-dev` / numeric version `30000`.
No production service was updated, no real device was commanded or flashed,
and no production signing key or signed release package was created.

## Source and screen

- The supplied ZIP remains unchanged. SHA-256:
  `76A902870EBE021B499EC32C870B5D2FEBBF5E8A042CE534B23D4F6322EF4FB5`.
- User-confirmed screen: TJC8048X550_011C. The official editor identifies the
  corresponding project target as TJC8048X550_011, 800x480 landscape, GB2312.
- Installed USART HMI 1.68.1 compiled both the original and the new independent
  project with **0 errors, 0 warnings**. Original UI sources were not replaced.
- New project: `firmware/instruments/hmi/washer-v3.HMI`, 7,945,366 bytes.
  SHA-256: `37E1949153EA0829D41914C99E61341F43DE1D47E6F74DFD90405B74E936C32B`.
- Exported screen image: `firmware/instruments/out/hmi/washer-v3.tft`,
  1,444,392 bytes. SHA-256:
  `AB0ED6D9E36833C6AB87A4806A99EA28AC05611F0A80E62D7E70EEC272BEB402`.
- The official simulator rendered the actual ESP32 drawing-command fixture
  with synthetic program, temperature, step and progress values. Its viewport
  clipped the bottom of the 480-pixel display. This was a representative visual
  check, not full-screen/all-state or physical touch acceptance.
- Source and TFT were saved; the new project was closed normally in the editor.

## Checks passed

| Check | Result |
| --- | --- |
| `python tools/test_instrument_core.py` | 53 control/scheduling checks and 21 UI parser/render/confirmation checks passed |
| Instrument virtualenv: `python -m unittest discover -s core_tests -v` | 28 tests passed, including contract and signed-package tests |
| `python -X utf8 tools/check_i18n.py` | 972 source terms, 4 catalogs, no missing translations |
| Python `compileall` | Passed for core, models, controllers, tests and new tools |
| `git diff --check` | Passed; Windows LF/CRLF informational warnings only |
| PlatformIO heater and washer cross-compilation | Both passed |
| Native Odoo IoT module tests on imytestlan | 87 tests, 0 failed, 0 errors |

The latest native Odoo test used a fresh synthetic database
`iot_instruments_1af01a2231b9`; its remote log is
`/tmp/iot_instruments_1af01a2231b9/test.log`. The 87-test result is the actual
test result; Odoo's separate 111-entry statistics include setup accounting.
The test service was bound to localhost, with separate addon/data paths,
workers and cron disabled, and stop-after-init. No existing database was cloned
or upgraded. Test artifacts were retained for diagnosis.

The LAN Odoo installation reports inconsistent auto-install states for its
social connector modules. The IoT tests nevertheless passed. This is an
environment limitation, not evidence that the entire LAN Odoo installation is
clean. No unrelated server modules were repaired.

Covered cases include device/company isolation, read-only permissions,
authentication, bounded requests, duplicate-event integrity, transaction
rollback, invalid-temperature exclusion, command expiry/exact acknowledgments,
immutable program versions, output shutdown, interlocks, motor-coasting wait
protection, bounded touch parsing and repeated-tap start confirmation.

## Firmware builds

Command: instrument virtualenv `python -m platformio run --project-dir firmware/instruments`.
Both binary identities were read back by the package tool and match version 30000.

| Target | RAM | Linked flash | Application image |
| --- | --- | --- | --- |
| ESP8266 heater, provisional NodeMCU 4MB profile | 31,332 / 81,920 bytes | 457,587 / 1,044,464 bytes | 461,744 bytes |
| ESP32 washer, 4MB, no PSRAM | 53,804 / 327,680 bytes | 1,073,569 / 1,769,472 bytes | 1,080,144 bytes |

Heater binary: `firmware/instruments/.pio/build/heater/firmware.bin`.
SHA-256: `1255397572AF7CD9E666F2F6CD7A20146A48D601DDC732DB563DB736FC4315D0`.

Washer binary: `firmware/instruments/.pio/build/washer/firmware.bin`.
SHA-256: `FC25B978215C73FF96761EBAB90456A9CB7C1160B5FB60A2766606542799D575`.

External SDK/dependency warnings were observed, including ESP8266 Python escape
sequence warnings. Compilation success does not certify timing, motor motion,
electrical polarity, available runtime heap or thermal performance.

## Remaining acceptance gates

1. Confirm the heater board/flash, actual wiring, relay polarity, sensor ROMs,
   PCF8574 expansion and independent thermal cutoff. Do not flash a guessed map.
2. Confirm washer home direction, pump routing, driver enable polarity, SD bus,
   door input, actual rotor stop time and physical safety interlocks.
3. Run physical OTA and SD tests, including interruption, wrong signature,
   wrong hardware and downgrade rejection. Host signature tests do not exercise
   the MCU crypto/update implementation. Dual OTA slots do not prove rollback.
4. Commission both MCU and HMI together by a controlled first wired installation.
   The legacy firmware does not acquire OTA support merely by updating Odoo.
5. Validate all screen states and real touch packets. Current candidate is
   English-only and edits programs in Odoo; legacy local program editing is not
   yet ported. Native Odoo views passed installation, but no new browser visual
   acceptance was performed for these two workspaces.
6. Validate TLS peak heap, offline journal recovery, queue-full handling, flash
   endurance and long-running temperature control. Heater capacity is currently
   about 128 minutes of one-minute samples; full storage stops operation.
7. Perform the commissioning checklist before any production release. No Odoo
   Knowledge articles were published because these are not accepted production
   interfaces. Multilingual repository manuals describe the candidate boundary.

See [commissioning checklist](INSTRUMENTS_V3_COMMISSIONING.md).
