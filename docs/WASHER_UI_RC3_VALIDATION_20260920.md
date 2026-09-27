# Washer Field-Test UI 3.5.0-rc3

Historical validation record. This ESP32-drawn UI is superseded by the native
V4 screen plus controller `3.6.0-rc3` pair installed on 2026-09-22. Do not use
the initialization, local-arm or screen-update statements below as current
operator instructions; use `WASHER_NATIVE_UI_REDESIGN_20260920.md` and
`WASHER_DEVICE_PUMP_TIMES_20260920.md`.

## Scope

English-only ESP32-drawn UI using the existing TJC Verdana Bold font resource.
No new TFT, pin mapping, motor speeds, pump PWM, platform schema, device identity,
Wi-Fi credentials or local pump settings are introduced by this update.
Physical actuator power was confirmed disconnected by the operator before flashing.

## Review Changes

- Separate step, cycle and remaining-time fields. Waiting keeps the current step visible.
- Show positioning/return/deceleration phases instead of a misleading zero countdown.
- Reserve two lines for program names and actionable notices.
- Remove overlapping Device Care text and make navigation controls visibly distinct.
- Tint editable Wi-Fi fields. Identify the device IP as DHCP, not server configuration.
- Distinguish saved connection configuration from live online status.
- Implement actual keyboard cancel/keep, clear its temporary password buffer, mask long passwords.
- Label unsaved settings `DISCARD / BACK`; repeated unchanged pump saves do not increase revision.
- Indicate blocked start, inactive run-time navigation and unavailable fault reset visually.
- Report homing/motion/storage faults and failed initialization; reset never starts a run.

## Verification

- 73 Python tests passed.
- 530 native control checks and 191 UI checks passed; setup, catalog, pump timing and heater panel suites passed.
- Added full nine-step offline example execution, indefinite manual wait, positioning gates,
  fill/overflow versus joint drainage outputs, reversal, spin-down and STOP/no-resume checks.
- ESP32 washer and ESP8266 heater builds passed. This release flashes the washer only.
- All 11 pages rendered from real C++ display commands with matching Windows Verdana Bold
  at 24 px; bounds and text-overflow checks passed. This is a layout approximation,
  not a photograph or proof of the TJC rasterizer's physical appearance.
- Preview command streams and layout receipt: `deploy/artifacts/instrument-screen-commands.txt.page*.txt`
  and `deploy/artifacts/washer-ui-layout-receipt.json`.
- Application SHA-256: `371f6e528f17b8c6a9c377cab3334a4e236a817261f82aeca52d6fe58be3ae92`.
- Verified pre-update 4 MB backup: `D:/Codex/device_backups/washer_20260920_105723`.
  Contains private settings; never add it to a repository or publish it.
- USB application update verified the new application, preserved first 64 KB and
  the entire second application/filesystem region against the fresh backup.
- Actual boot receipt: `deploy/artifacts/washer-field-test-boot-20260920-110214.json`.
  Program revision 3 and A/B=10 seconds (settings revision 2) restored before clock/network
  synchronization. No automatic initialization, arming or actuator output occurred.
- `deploy/artifacts/washer-ui-rc3-stability.json`: 88 samples over 179.028 seconds,
  one boot, all outputs off, screen/storage healthy, then valid time and catalog HTTP 304.
- Current imytestth isolated UI regression passed 12 responsive language/size scenarios
  plus 3 heater, 3 recipe and 3 program-selection forms. No production test runner used.
- Chinese/Thai internal Knowledge articles 1186/1187 and screenshot attachments
  13187/13188 updated and verified; not publicly accessible.
- Final read-only production ORM verification reports firmware `3.5.0-rc3`,
  `online=true`, `status_fresh=true`, matching catalog hash, preserved pump settings,
  and `locally_armed=false`. Receipt: `deploy/artifacts/pump250-sample-verify.json`.

## Physical Acceptance Still Required

Use the bilingual checklist in `WASHER_DEVICE_PUMP_TIMES_20260920.md`.
Software does not measure delivered volume, detect balanced loading, verify liquid removal,
or prove mechanical position from step counts. Initialization, local arming and loading
reference checks remain mandatory; firmware does not silently mark the unit commissioned.

The heater shares tested platform interfaces and compiles successfully, but no heater was
connected or flashed in this change. Actual heater protection and thermal performance must
be tested separately under supervision; do not infer acceptance from the washer results.
