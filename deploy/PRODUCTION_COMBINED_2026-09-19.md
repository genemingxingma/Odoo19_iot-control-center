# Combined platform release, 2026-09-19

## Authorization and scope

The user authorized updating imytestth and directed all future server testing to
isolated databases on that host, not imytestlan. Project AGENTS.md and the test
helpers now enforce this policy. Tests use synthetic data, separate addon/data
directories, loopback ports, disabled cron/email and restricted preview egress.

Odoo `19.0.2.1.1` and the receipt bridge are deployed. This is not an instrument
firmware release or physical acceptance. No device was flashed, switched or
unlocked; no unknown gateway address was assigned to a company. No history was
discarded. Heater/washer registries remain empty until hardware commissioning.

The platform adds heater settings/history and washer program/run-log workspaces.
Independent receipt lanes prevent unknown environmental traffic blocking relay
and network reports. Whole-report freshness guards prevent old telemetry from
regressing state. Protection status is distinct from schedule synchronization;
the overview content owns its scroll area.

## Tested and deployed artifacts

- R1 addon SHA-256: `f9258fe5f11a64430096996910ebca94d848d5eb95f4aa68ca4cefc0c9b927c4`.
- Final R2 addon SHA-256: `f52b4d5deb1142686d6272a057cce778a1f8b9edcb4a5c5020e9424cae74a42f` (133 runtime files).
- Bridge source SHA-256: `e211df6e7e779cb8decf85d16217cc4fdab449e4c71d532f0fd7ea3fc8d061d7`.
- Linux bridge binary SHA-256: `c062137300aca4bcce0b2a9a94ea5925369fce1d4f484bd53803be47a60c7380`.
- Native upgrade test DB: `iot_instruments_upgrade_20260919091947` on imytestth.
- R1 native evidence: `/opt/odoo/module_backups/iot_instruments_test_20260919_091947`.
- R2 UI evidence: `/opt/odoo/module_backups/iot_instruments_test_20260919_094231`.

The isolated upgrade passed 97 Odoo post-tests (123 including subtests), zero
failures/errors. Linux bridge tests passed 11 cases. Local Python core tests
passed 39 cases, and four translation catalogs cover 1020 terms.

Final browser validation passed nine responsive scroll scenarios (English,
Chinese and Thai at 1440, 960 and 390 pixels), plus all three single-probe heater
forms, with no JavaScript errors or document-width overflow. Synthetic test
screenshots are under `docs/images/`. Earlier compiled firmware/core simulations
remain candidate evidence only; see the commissioning checklist.

R2 changes only the obsolete two-channel overview description and its catalogs.
Its guard required exactly six allowed files and one literal Python description
replacement, with every other runtime byte identical to R1. It inherited R1's
native suite and reran all nine UI scenarios and three heater forms against R2.

## Backup and production verification

R1 started at 09:28:30 UTC and recovered at 09:32:46 UTC. Private backup:
`/opt/odoo/module_backups/iot_instruments_production_20260919_092830`.
It contains the verified 195471404-byte database archive, filestore, old module,
old bridge, durable outbox and protected configuration. Fifteen protected
business-table fingerprints matched before/after native upgrade; intentionally
added runtime fields and res_partner write audit timestamps were excluded.

R2 source-only rollback backup:
`/opt/odoo/module_backups/iot_wording_20260919_094755`.
Both release paths take the shared laboratory and IoT release locks. Do not
blindly restore the full R1 database over later unrelated releases or live writes;
assess point-in-time recovery and affected data before any rollback.

At 09:48:30 UTC, all 133 runtime files matched the final artifact and the bridge
matched its tested binary hash. Odoo, bridge, MQTT broker and OTA proxy were
active. Captured outbox accounting: 13442 events = 1153 committed + 12289 still
durable, zero missing. Rejected-event counts did not change. The relay bridge
queue drained; unregistered environmental events remain durable and retryable.

Production browser verification showed 11 registered/recent relays and zero
offline active relays. Actual scrolling reached scrollTop 663 with an 854-pixel
viewport and 1517-pixel content. The single-probe heater description and all six
workspaces were visible. Relay outputs were unchanged: 0676B5 ON, other ten OFF.
One existing background network synchronization created and confirmed network_set
for 934CD1 at 09:36:41 UTC; no ON/OFF, OTA or protection-reset command was issued.

A separate supply-catalog deployment stopped Odoo at 09:41:38 and restarted it
at 09:44:29 UTC. A Knowledge page returned 502 during that window and worked
after recovery. Deployment coordination confirmed this was not the isolated UI
test stopping production. The other task may subsequently restart Odoo for its
own authorized patch; this record describes the bounded IoT acceptance window.

Chinese, English and Thai internal Knowledge guides were created through Odoo
ORM as articles 1183, 1184 and 1185, with image attachments 13138, 13139 and 13140.
Readback verified all three; the Chinese production page and its 1440x900 image
were additionally verified in the browser. They are not public website articles.

## Unresolved and hardware-only work

- Washing Buffer Heater relay 06458F remains OFF with control_inhibit=true,
  no watchdog trip, valid clock and 14 schedule entries. This blocks its 09:00
  scheduled ON. Boot/manual OFF can set the inhibit; the earlier trigger is not
  proven. The release deliberately did not clear it or energize the heater.
- The environmental gateway's registered public source no longer matches
  incoming addresses. Last accepted reading is 2026-09-15 09:55:04 UTC; all 16
  probes remain stale. Verify the onsite gateway identity/address before mapping
  a new public IP or migrating to WireGuard. Unknown traffic was not discarded.
- Heater firmware uses the corrected single-DS18B20 source and a 600-second
  actual-heating window with rise strictly below 1 C triggering a latched fault.
  Flash size, probe ROM, output driver and independent thermal cutoff still need
  bench checks. No generic or previous dual-channel BIN is approved for flashing.
- Washer startup home/drain, local multi-program selection and explicit cycle
  counts remain unfinished; timed steps do not fulfill those requirements.
  First-install partition migration, OTA/SD interruption recovery, open-rotor
  loading/stop behavior and both instruments' physical acceptance remain pending.

See [the multilingual guide](../docs/IOT_19_0_2_1_1_USER_GUIDE.md) and
[commissioning boundaries](../docs/INSTRUMENTS_V3_COMMISSIONING.md).
