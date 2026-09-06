# Relay 2.0.2 Validation

## Scope

The user authorized relay switching tests in the unoccupied laboratory, followed by one-device-at-a-time firmware rollout after both hardware profiles passed. This record does not authorize a V2 Odoo/database cutover.

The two canaries, 0676B5 (IoT-Outlet) and DDC10E (IoT-Relay), passed the tests below. All 11 online relays completed serial OTA and restoration. Final fleet reconciliation passed at 2026-09-06 13:47:22 UTC (20:47:22 Asia/Bangkok). Two long-offline devices remain pending; this is not a claim that all 13 active inventory records were upgraded.

## Cause and Recovery

0676B5 was detectable after the user's power cycle but still reconnected roughly every 18 seconds. The broker retained a 989-byte, 14-entry `schedule_set` command, which was delivered again on every subscription. The same-source client replacement log was not sufficient to establish duplicate physical identities.

The retained message was backed up privately and temporarily removed from that one MQTT topic. Odoo schedules and device schedules were not deleted. The device then produced continuous telemetry and acknowledged OFF, ON and OFF commands. This isolated the failing retained-schedule path without requiring manual flashing.

The 2.0.1 compiled `publishStatus` frame occupied 2672 bytes. The schedule handler added 608 bytes, the command handler 288 bytes, and MQTT/driver/serializer calls shared the same 4096-byte continuation stack. Moving report JSON and serialization buffers off the stack removed this pressure. The corrected 2.0.2 application frames are:

| Function | Frame bytes |
| --- | ---: |
| publishStatus | 112 |
| publishTelemetry body | 112 |
| publishReport | 272 |
| applyScheduleSet | 608 |
| handleCommand | 288 |

The application portion of the schedule callback chain is 1280 bytes; this is not the complete driver call-stack size. `tools/check_relay_stack.py` checks the compiler `.su` output and reserves at least half the continuation stack for other calls. Both the JSON document and serialized output now use checked heap allocations; incomplete reports are not published.

Identical `schedule_set` content/version no longer rewrites the schedule file. Unidentified legacy commands no longer force an unchanged receipt write. Status and telemetry now include uptime, reset reason and free-stack watermark.

## Hardware Results

| Test | 0676B5 / IoT-Outlet | DDC10E / IoT-Relay |
| --- | --- | --- |
| HTTPS OTA from pinned 2.0.1 to 2.0.2 | Pass | Pass |
| Explicit OFF, ON, OFF, correlated command IDs | Pass | Pass |
| 3-second maximum-ON watchdog closes output | Pass | Pass |
| 8-second delay expires OFF | Pass | Pass |
| Same-ID delay replay does not cancel/restart timer | Pass | Pass |
| Expired ON is rejected | Pass | Pass |
| Original retained schedule restored and reconnect verified | Pass, 14 entries | Original zero-entry clear retained |
| Schedule version change and original configuration restore | Pass, version 4 to 5 to 4 | Not applicable, no schedules |
| Continuous 60-second telemetry/uptime check after tests | Pass | Pass |
| Final OFF and original maximum-ON value restored | Pass, 0 seconds | Pass, 0 seconds |

0676B5 reached 780 seconds uptime during the extended test, with a 1184-byte free-stack watermark after exercising the full schedule-write path. DDC10E reached 390 seconds uptime during its extended test; its final OFF report showed 1648 bytes free stack. Both emitted `PROBE_RESULT` with `passed=true`. Switching confirmation is device-reported, not an independent measurement of contacts or load current.

The direct MQTT trace also shows the original 8-second timer deadline survived replay: 0676B5 reported ON at 32.76 seconds, received the replay at 33.85, and reported OFF at 40.73. DDC10E reported ON at 8.32, received the replay at 9.33, and reported OFF at 16.28. These times are relative to each probe invocation, not wall-clock timestamps.

The original retained message was restored onto 2.0.2, followed by a company-network refresh that forced MQTT resubscription. It did not recreate the reconnect loop. The recovered unit does not currently require manual flashing. Firmware 2.0.1 / record 15 remains quarantined and must not be used for further rollout.

## Diagnostic Corrections

V1 telemetry sampling can update an existing message row. Ordering by row ID caused a later configuration acknowledgement to be missed even while the device was healthy. Inventory and rollout helpers now order by `received_at desc, id desc`. Ingest coalescing could still hide an intermediate acknowledgement, as seen while restoring device 57. The rollout helper now subscribes to that explicit device's live MQTT reports, rejects retained reports, and requires the exact command ID and expected configuration/state. Odoo device state is still cross-checked; a row-order change alone is not the acknowledgement gate. Device 57's restore passed with this direct observer before rollout resumed, without another OTA.

The command probe initially stopped on DDC10E's normal retained `schedule_clear`. Its reviewed allowlist now accepts that form only for a zero-schedule baseline with the same schedule version. The successful extended test was rerun after this correction; the earlier rejected test is not counted as a pass.

Device 63's first post-OTA `network_set` did not confirm within 90 seconds, even with the direct observer. Read-only inspection showed stable increasing uptime, unchanged previous command identity, an empty configuration revision and OFF with scheduled control inhibited. This was not counted as a logging-only timeout. A separate restore-only invocation then confirmed the company revision, original OFF state, 4500-second maximum and ten schedules; no second OTA was sent. The cause of that single missing application acknowledgement was not established. It remains an example of why V1 publication alone is not delivery proof.

## Final Fleet Reconciliation

The 75-second read-only MQTT observation required at least two fresh, non-retained telemetry reports per device. All reports matched the firmware, board, identity, company configuration revision, original state, schedule count and maximum-ON limit. Scheduled control was enabled, with no active delay or safety trip. Reported MQTT routing matched the company primary private endpoint. Uptime followed elapsed observation time without a reboot discontinuity. This bounded observation is not a long-duration soak test.

| ID | Serial | Board | Before / after | Schedules | Maximum ON seconds | Last observed uptime seconds |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 11 | 934CD1 | IoT-Relay | OFF / OFF | 0 | 4500 | 2040 |
| 39 | DDC10E | IoT-Relay | OFF / OFF | 0 | 0 | 2610 |
| 55 | 067702 | IoT-Outlet | OFF / OFF | 10 | 4500 | 1890 |
| 56 | 0645EE | IoT-Outlet | OFF / OFF | 10 | 4500 | 1680 |
| 57 | 06458F | IoT-Outlet | OFF / OFF | 14 | 0 | 1470 |
| 58 | 06463E | IoT-Outlet | OFF / OFF | 10 | 4500 | 870 |
| 59 | 0676B5 | IoT-Outlet | OFF / OFF | 14 | 0 | 3450 |
| 60 | 0646EE | IoT-Outlet | OFF / OFF | 10 | 4500 | 780 |
| 61 | 064708 | IoT-Outlet | OFF / OFF | 10 | 4500 | 630 |
| 62 | 0675A0 | IoT-Outlet | OFF / OFF | 10 | 4500 | 450 |
| 63 | 0645E4 | IoT-Outlet | OFF / OFF | 10 | 4500 | 330 |

The current-round snapshots were captured separately immediately before each 2.0.2 upgrade. In particular, the old 2.0.1 ON snapshot for device 59 was not restored after its scheduled closing time. Protected evidence is in `/opt/odoo/iot-v2-isolated-20260906/relay-rollout/fleet-2.0.2-final.json`, with per-device snapshots alongside it; these runtime files are not committed.

Device 37 / 93DB97 last reported at 2026-07-14 03:30:36 UTC, and device 38 / 93CD99 at 03:13:52 UTC that day. Both remained offline on 1.8.8. Bring them online and validate their board/layout before attempting OTA; no blind update was queued.

After the audit, `odoo`, `iot-bridge`, `iot-ota-proxy` and `mosquitto` all reported active. The production module was still `19.0.1.0.19`.

## Build and Deployment Boundaries

- Firmware record: 16, version 2.0.2, 479120 bytes.
- SHA-256: `1af36e7bc1e5a56c79a62e901f000b1c1cf72dbebfee0339911619e92f86b651`.
- ESP8266 1MB/DOUT/64KB filesystem layout retained; no filesystem upload or whole-chip erase.
- RAM: 34508/81920; Flash: 474971/958448.
- PlatformIO build, stack gate, 25 C++ protocol assertions, 7 core tests and translation checks passed.
- Company-derived MQTT/OTA endpoints, country/timezone behavior and per-device stored configuration were not replaced with compiled deployment addresses.
- The firmware stays in the one-way V1 migration mode for current production devices. It does not add missing sequence/expiry/identity fields to old controller traffic. Full V2 delivery guarantees require the matching backend/bridge cutover.
- Production Odoo remains 19.0.1.0.19. No production module/bridge replacement, database history reset or service restart was performed in this firmware operation.
- Offline devices 93DB97 / ID 37 and 93CD99 / ID 38 remain pending; their hardware details cannot be validated from stale 1.8.8 reports.
- Preserve the known previous production firmware record 14 / 1.8.10 as a protected fallback; do not publish its binary or embedded deployment configuration.

`tools/relay_rolling_update.py` creates a distinct protected `device-{id}-to-2.0.2.json` snapshot before each upgrade. A source/board/timer mismatch or missing restoration confirmation stops that device's operation. Old ON snapshots older than ten minutes are rejected; operators must also review intervening schedules before any manual restoration.
