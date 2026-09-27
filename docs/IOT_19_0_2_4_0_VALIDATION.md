# IoT 19.0.2.4.0 validation

Validated and published to imytestth on 2026-09-20 (Asia/Bangkok), after explicit
user approval. Production was upgraded from 19.0.2.3.0 to 19.0.2.4.0 using the
exact tested artifact below.

## Evidence

- Local Python core: 71 tests passed.
- Native device-independent C++ regression: 530 control checks, 168 screen
  checks, heater panel, washer setup and catalog suites passed. No device flashed.
- Odoo upgrade rehearsal from installed 19.0.2.3.0 to candidate 19.0.2.4.0:
  106 post-install tests, zero failures/errors. Synthetic database
  `iot_instruments_upgrade_20260919171111` on imytestth only.
- Protected record hashes for 17 tables remained unchanged across the upgrade,
  including instruments, programs, program steps, instrument commands and firmware.
- Browser checks: English, Simplified Chinese and Thai at 1920x1080, 1440x900,
  1366x768 and 390x844. All 12 cases passed without horizontal overflow.
  The three desktop sizes require no overview scrolling; mobile scrolls normally.
- All three languages passed heater form, program editor, and selection/save/reload
  checks through the real Odoo UI. Program selection does not queue a start command.
- Four translation catalogs validated against 1083 source terms.
- The 134 packaged source files match the tested artifact byte-for-byte.

Artifact SHA-256:
`65f7c80839657dc71e0e9ab3be2f3a0ac3c41fea0297e8841982d3e11c8e3535`

Server evidence directory:
`/opt/odoo/module_backups/iot_instruments_test_20260919_171111`

Local UI evidence directory:
`deploy/artifacts/combined-ui-imytestth-20260919-r240`

## Production publication

- Maintenance started at 08:22:34 and services recovered at 08:26:34 on
  2026-09-20 (Asia/Bangkok; receipt timestamps are UTC).
- Database archive integrity was checked with pg_restore. The filestore,
  addon source and bridge binary backups were verified before installation.
- Protected record hashes for 20 tables remained unchanged, including
  installed laboratory models. Native views and program defaults passed checks.
- Independent post-release verification confirmed all 134 installed source
  files match the tested archive, all four services (Odoo, IoT bridge,
  Mosquitto and OTA proxy) are active, and the Odoo health endpoint passes.
- The bridge binary and environment were unchanged. The release runtime
  check reported zero new relay commands and zero ingest errors.
- The latest stored temperature/humidity reading reported by the runtime
  check was `2026-09-15 09:55:04.585000` (UTC). Recent monitoring data has
  therefore not been verified; this release does not establish that the
  temperature gateway is reporting normally. No source IP was rebound.

Verified backup and server release evidence:
`/opt/odoo/module_backups/iot_instruments_production_20260920_012234`

Local release receipt:
`deploy/artifacts/instruments-production-receipt.json`

## Boundaries

All browser records and test device reports are synthetic. This is not evidence
that a real washer received a program or passed physical commissioning.
This was a platform-only release. No relay switching, protection reset, gateway
rebinding, device flashing or real instrument run was performed.
Isolated previews used loopback ports, restricted egress, disabled cron/email and
separate data/addon directories. Preview services were stopped after UI validation.
