# Combined candidate, 2026-09-19

Platform release completed on 2026-09-19 as `19.0.2.1.1`. This document retains
the pre-release diagnosis and scope. See the final [production acceptance](../deploy/PRODUCTION_COMBINED_2026-09-19.md)
for deployed hashes, backups, verification and unresolved operational items.

Release authorization (2026-09-19): update imytestth with the combined platform
candidate after isolated upgrade testing on that host. No further imytestlan
tests. Do not deploy the isolated 2.0.9 checkout separately. Device flashing,
switching, protection resets and gateway IP rebinding are excluded.

## Production diagnosis (read-only)

- All 11 active relays emitted fresh non-retained MQTT telemetry at 08:31 UTC.
  Their primary MQTT connections were intact. No device commands were sent.
- Approximately 13,200 durable events were pending: about 12,075 temperature
  gateway events, 1,115 relay events and 18 access-point events at 08:33 UTC.
- The registered public gateway source no longer matched incoming source IPs.
  No company/IP binding was reassigned automatically. Unknown gateway events
  returned a retryable result; sequential retries delayed other device classes.
- Ancillary relay report handlers accepted older receipt timestamps and could
  regress last_seen even when the relay-state handler rejected stale state.
- Washing Buffer Heater (06458F) reported OFF, control_inhibit=true,
  safety_trip=false, time_synced=true, schedule_version=4, schedule_count=14.
  Its configured daily times remain 09:00 ON / 19:00 OFF, Asia/Bangkok.
  Current firmware sets the inhibit on boot and manual OFF. This is the proven
  immediate reason scheduled ON is blocked. No durable reason code proves
  which earlier action set it; do not claim an identified power outage.
- The overview action was 855px high with 1152px content. Odoo's action rule
  won over overflow:auto, leaving overflow:hidden. The child now owns scrolling.

## Candidate changes

- Independent relay, environment, network and other receipt workers, with
  separate queue cursors. Failed events stay durable; successful matching ACKs
  alone remove pending files. Invalid events remain quarantined.
- Whole-report stale gating and guarded auxiliary handlers. Serialization
  conflicts retry rather than labelling valid telemetry permanently erroneous.
- Card, list and form distinguish schedule synchronization from execution
  permission; unknown/stale flags are not presented as ready.
- Heater source profile corrected to a single DS18B20, OLED and three keys.
  Heater protection uses rise < 1 C after 600 seconds of actual heating.
- Offline ordinary heater samples form a bounded rolling buffer (roughly
  112 minutes at one-minute sampling, less with queued alarms). Overwrite count
  is persisted and reported. Alarms/command receipts are not evicted; true
  storage errors or critical-log exhaustion still stop the device.

## Verification and release gates

Reliability-only checkout: 81 native Odoo post-tests on imytestlan, zero
failures/errors, synthetic database iot_reliability_ee49270abee7. Windows Rust
tests: 9 passed, including a delayed HTTP sensor endpoint while relay ACK
completes within one second and the sensor event remains on disk.

Combined candidate verification is recorded during this task; compilation and
simulated tests are not physical acceptance. Never flash withdrawn heater
profiles. Original heater Flash size, DS18B20 ROM/power, output driver and
independent overtemperature cutoff need bench verification. First-time washer
partition migration and OTA/SD interruption recovery also require a bench test.

The earlier outstanding washer software features are now implemented in
`3.4.0-rc3`: startup home/drain, local multi-program selection and explicit
forward/reverse cycle counts. Platform `19.0.2.2.0` adds program authoring and
automatically prepends safe homing. Physical commissioning remains pending.
Public gateway identity needs verified site configuration, preferably
a stable WireGuard source; do not auto-trust a newly observed public IP.
