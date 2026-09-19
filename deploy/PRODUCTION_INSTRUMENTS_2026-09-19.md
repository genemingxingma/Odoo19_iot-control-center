# Instrument completion release, 2026-09-19

## Scope and authorization

The user authorized completing the array-washer and buffer-heater functions,
refreshing the connected washer over USB and updating imytestth after isolated
validation. Server testing used only new synthetic databases on imytestth. The
production database was not used for tests and imytestlan was not used.

Odoo `19.0.2.2.0` completes washer program authoring, immutable revisions,
authoritative full-catalog synchronization, run logs and heater controls. The
heater interface is `heater-control-v1`: the platform may configure, stop and
request signed OTA, but cannot start heating. Local SW2 remains the only heating
enable. The default no-rise protection is 600 seconds of accumulated active
heating with a rise below 1 C; exactly 1 C does not trip it.

Program authors enter only process steps. Publishing prepends a safe homing step.
The validated typical process is Fill A, operator wait, wash cycles, drain,
Fill B, wash cycles, drain and spin dry. A drained A fill may be followed by B;
changing liquid or spin drying before drainage is rejected. New wash and spin
steps default to the original 1 and 10 rev/s settings.

## Acceptance evidence

- Final addon: 133 runtime files, SHA-256
  `2c1bb8238397855cbf45f6688e3011c119e3571c68d00cb1d8cc594da0d606ce`.
- Bridge source SHA-256:
  `bcdd87f369d78665174c9ce994e413fcbb368020e7da68d8e666169619cf5f50`.
- Linux bridge binary SHA-256:
  `c062137300aca4bcce0b2a9a94ea5925369fce1d4f484bd53803be47a60c7380`.
- Isolated upgrade DB: `iot_instruments_upgrade_20260919130409`.
- Isolated evidence root:
  `/opt/odoo/module_backups/iot_instruments_test_20260919_130409`.
- Upgrade from the actual production `19.0.2.1.1` source passed 101 Odoo
  post-tests (127 including subtests), zero failures/errors. Fifteen protected
  business-table fingerprints were unchanged. The bridge passed 11 tests.
- Real browser validation passed English, Chinese and Thai at 1440, 960 and
  390 pixels: nine scroll scenarios, three heater forms and three washer-program
  forms. There was no document-width overflow. The test caught and blocked two
  untranslated program paragraphs and stale speed wording; the corrected
  candidate passed the complete rerun.
- Local validation passed 71 Python tests, 526 native safety checks, 168 screen
  UI checks and four translation catalogs covering 1028 current source terms.

## Production deployment

Production maintenance started at `2026-09-19 13:13:01 UTC` and recovered at
`2026-09-19 13:16:57 UTC`. The private rollback package is:

`/opt/odoo/module_backups/iot_instruments_production_20260919_131301`

It contains the database dump with integrity check, filestore, prior addon,
prior bridge, protected configuration and durable outbox. After release:

- Odoo reports `19.0.2.2.0` installed.
- `odoo`, `iot-bridge`, `mosquitto` and `iot-ota-proxy` are active.
- All 133 addon files and the bridge binary match the accepted hashes.
- No relay command or IoT ingest error was created by the release.
- The instrument, instrument-command and instrument-firmware registries remain
  empty until individual equipment is commissioned.
- All 12,880 outbox events captured before restart were accounted for; 12,880
  remained durable and none were missing.
- Knowledge articles 1183, 1184 and 1185 were updated in Chinese, English and
  Thai with verified current-interface screenshot attachments. They remain
  internal and are not website-public.

## Device artifacts and limits

The connected ESP32 washer was updated over COM4 to `3.4.0-rc3`. The 1,111,536
byte application SHA-256 is
`b63104d10c71bcf9da2c458d36d1e427775e3dc44a58f3ff3cc5639f311e6559`.
Application and partition-table readback verification passed. Runtime sampling
confirmed the paired screen, Wi-Fi, storage, journal and temperature probe were
healthy; commissioning and platform enrollment were false, the program catalog
was empty and all pump/motor outputs were zero. The existing TFT did not need a
second flash because the new palette is drawn by the ESP32 application.

The ESP8266 heater `3.2.0-rc1` candidate builds to 476,768 bytes, SHA-256
`5ea86c3514cb10a66915d5ed181598747dc8a5d5569a7dbefde87d02f1a681d0`.
It was not flashed because no heater was connected for Flash, output-polarity,
probe-ROM and loaded-heater verification. Compilation and platform compatibility
are not physical acceptance. Do not commission either instrument until the
onsite checks in `docs/INSTRUMENTS_V3_COMMISSIONING.md` are complete.
