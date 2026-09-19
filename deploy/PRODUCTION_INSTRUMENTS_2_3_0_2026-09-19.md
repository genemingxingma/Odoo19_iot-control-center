# IoT Instruments 19.0.2.3.0 Production Release

## Scope

Odoo `19.0.2.3.0` was deployed to imytestth on 2026-09-19. The release completes
the heater and washer management workspaces, authoritative washer program
catalog synchronization, bounded telemetry acknowledgements, temperature time
quality, run logs, relay receipt ordering and overview scrolling corrections.

The washer screen is English-only. Odoo remains translated in Chinese, English
and Thai. Company country, timezone and private network settings remain owned by
company configuration and are not compiled into instrument firmware.

## Validation

- Upgrade rehearsal database: `iot_instruments_upgrade_20260919150838`.
- Odoo test result: zero failures and zero errors.
- Protected business tables: 15 fingerprints unchanged during rehearsal and
  production upgrade.
- Bridge: 11 tests passed; deployed binary SHA-256
  `c062137300aca4bcce0b2a9a94ea5925369fce1d4f484bd53803be47a60c7380`.
- Browser acceptance: Chinese, English and Thai at 1440, 960 and 390 px; all
  nine scenarios scrolled vertically without horizontal overflow or JavaScript
  errors. Three heater forms and three washer forms passed.
- Local software: 71 Python tests, 530 native safety checks and 168 UI checks.
- Translation validation: 1,042 source terms across four catalogs.

The release package contains 133 files and has SHA-256
`c405077a071765ddb738100855e583eab260f5842e5c4244ffcb4615cf67e6ea`.

## Production Result

- Maintenance window: 2026-09-19 15:28:13 to 15:32:07 UTC.
- Rollback backup:
  `/opt/odoo/module_backups/iot_instruments_production_20260919_152813`.
- Services after recovery: Odoo, IoT bridge, Mosquitto and OTA proxy active.
- Online module files: all 133 match the candidate package byte-for-byte.
- New relay commands created by the release: zero.
- Ingestion errors during bounded verification: zero.
- Instrument registries remain empty until each physical device is explicitly
  registered and commissioned.

Existing relay states and control-inhibit flags were preserved. The release did
not energize relays, motors, pumps or heaters. The environmental gateway's last
reading was already stale before this release and remains a separate operational
issue.

## Device Boundary

The connected washer ESP32 and TJC screen were updated separately to the paired
`3.4.0-rc5` build with actuator power isolated. See
`docs/WASHER_USB_RC5_RELEASE_20260919.md`.

The heater `3.2.0-rc2` build passed compilation at 478,224 bytes with SHA-256
`7b0c756f52a5c5f9ff6d3406590c8cb9b75e4f0a264342056f622e6e2b61f493`.
It was not flashed because no heater was connected and its actual board, output
polarity, DS18B20 ROM and OTA public key have not been commissioned against this
build.
