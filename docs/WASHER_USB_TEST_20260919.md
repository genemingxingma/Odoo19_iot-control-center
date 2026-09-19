# Washer USB test, 2026-09-19

## Scope

One ESP32-D0WD-V3 rev 3.1, 4 MB/no PSRAM, and its TJC8048X550_011C
screen were flashed over the controller's CH340 USB connection. The user
confirmed the screen was powered and motor/pump power was isolated. Software
commissioning and loading calibration remain disabled. This is not motor,
liquid-handling, mechanical-safety, OTA, or SD-update acceptance.

Production was not changed during this USB test. Server integration used only
the synthetic `iot_instruments_2031dd5c5ef9` database on imytestth, separate
addons/data, loopback Odoo ports, disabled cron, and restricted egress.

## Artifacts and preservation

- Original 4 MB Flash was backed up and verified before writing. SHA-256:
  `8385a6cf347d9269adcce17bb6ca298e055b93f89f1a7b8798e38c77d01308ce`.
- The first migration installed the new bootloader/partition table/application
  and a separately provisioned LittleFS image. Original NVS at `0x9000` was
  preserved and separately verified. Later application writes touched only
  `0x10000` and were verified before rebooting.
- Final application: `3.4.0-rc3`, 1,111,536-byte BIN, SHA-256
  `b63104d10c71bcf9da2c458d36d1e427775e3dc44a58f3ff3cc5639f311e6559`.
  Static RAM: 54,060 bytes. Linked application: 1,104,965 bytes of the
  1,769,472-byte OTA slot. This BIN alone is not a first-install package.
- Screen TFT: 1,444,392 bytes, SHA-256
  `ab0ed6d9e36833c6ab87a4806a99ea28ac05611f0a80e62d7e70eec272beb402`.
  All upload blocks were acknowledged; two V3 heartbeats were required after
  transfer. Receipt: `deploy/artifacts/washer-screen-flash-20260919-v2.json`.
- Private backups, device credentials and signing keys are outside the repo
  in an ACL-restricted backup directory. Never publish the filesystem image.

## Corrections found during hardware testing

1. LittleFS needed the explicit `littlefs` partition label; Arduino's default
   `spiffs` label did not match our table. Failure did not autoformat storage.
2. The program-library page now permits idle automatic synchronization. Wi-Fi
   editing still defers catalog changes. Pending selection stays bound to
   program identity and stale held presses are invalidated on catalog changes.
3. Wi-Fi/time becoming ready schedules an immediate catalog check instead of
   waiting for the next periodic interval.
4. The screen reported capacity `128974848-0`. The uploader accepts this exact
   observed variant only, after repeated model/capacity verification; arbitrary
   suffixes are rejected. No undocumented suffix semantics are assumed.
5. Physical open-rotor layout is distinct from permission to drive outputs.
   The USB diagnostic reports layout without bypassing commissioning gates.

## Screen and regression checks

The screen uses a darker blue header, pale blue background, light-blue
secondary buttons, blue primary actions and a distinct red STOP button. White
surfaces are reserved for data-entry fields rather than white-on-white buttons.
Redundant open-rotor/lid labels,
temperature `(read only)`, chip specifications, idle zero countdown and idle
output prose were removed. Actionable faults, loading balance checks, movement
warnings and the setup lock remain. Touch locations and output permissions did
not change. The user's pre-theme photo confirmed the paired UI and actual
temperature rendering; no post-theme photograph has yet been inspected.

Local validation: 526 native safety checks, 168 UI checks, 71 Python core tests,
heater-panel, washer-setup and catalog-parser suites passed. Four translation
catalogs validated with 1,028 source terms. ESP32 build and USB application and
partition-table readback verification passed.

## Device integration evidence

- Screen heartbeat, Wi-Fi, time, filesystem and journal were healthy. DS18B20
  reported approximately 25.1-25.4 C. All sampled pump/motor outputs remained
  zero and commissioning remained false.
- Eight released synthetic programs synchronized from the isolated Odoo API.
  Initial canonical catalog SHA-256:
  `39b1c1f79b972de391d3b1c297f03da77881204885750fe7897060ed14f32f93`.
- Publishing revision 2 of program 1, archiving program 2 and adding program 9
  changed the device catalog atomically, retaining eight programs and selection
  identity. Device and server SHA-256 matched:
  `26f87f1eba888aa05d35a5010d7f87a8784a6f4306d23ee2335bae02549c5159`.
  Receipt: `deploy/artifacts/washer-usb-test-mutated-after-service-restart.json`.
  An isolated Odoo registry reload delayed this check; only the test HTTP unit
  was restarted. No production restart or module changes were performed.
- Stopping the temporary proxy made the platform unreachable while Wi-Fi stayed
  connected. The complete list and selected revision remained, including after
  a controller reset. Receipt:
  `deploy/artifacts/washer-usb-test-offline-reboot.json`.
- A verified empty platform catalog cleared the list and selection, rather
  than being confused with an unreachable server. Device/server SHA-256:
  `986708e87df8b9723981850bf58f60d9fd42fb7a567e9ed893af581523a793a5`.
  Receipt: `deploy/artifacts/washer-usb-test-empty-authoritative.json`.

## Cleanup and handoff

The isolated HTTP unit and local TLS/SSH proxy were stopped; the temporary
Windows firewall rule was removed. The isolated HTTP port was verified closed.
The device filesystem was then replaced with a verified clean image containing
only locked hardware configuration, the saved Wi-Fi profile and the OTA public
key. Temporary endpoint/token/certificate, synthetic recipes and test journal
were removed from the device, with private backups retained outside Git.
Application readback verification passed again after filesystem cleanup.

Final rc3 receipt `deploy/artifacts/washer-usb-test-rc3-final.json` confirms:
firmware rc3, healthy storage/journal, screen heartbeat, Wi-Fi connected, valid
temperature, zero programs, no platform enrollment and all outputs off.
Production enrollment must follow catalog API deployment and commissioning;
the device is intentionally not left pointing at the stopped temporary server.

Physical startup, motion direction, loading angles, pump flow and balance still
require commissioning with the operator. Actual touch-keyboard credential entry,
signed OTA and SD installation were not exercised by these USB tests.
