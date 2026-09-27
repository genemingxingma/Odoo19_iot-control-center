# Heater rc8 validation - 2026-09-27

## Root Causes and Behavior

The rc6 cached startup-only probe inventory could remain zero despite valid
addressed reads. rc7 fixed GPIO initialization, bounded repeated single-pass
enumeration, matching/CRC/power checks and powered-only loop protection.
Physical rc7 samples confirmed the probe recovery and no new loop trips.

The subsequent storage alarm was traced to the protected preflash filesystem,
not to probe damage. A read-only LittleFS inspection found 125/125 blocks used,
116 ordinary temperature records, two critical events and a stored `storage`
fault. Old limits of 128 ordinary / 192 total entries could not fit this geometry.

rc8 sizes the heater cache from real filesystem block geometry, reserving 32
blocks for metadata/configuration/temporary writes. This device's limits are
62 queued ordinary/critical entries for ordinary-record rolling and 93 total
entries. Only validated ordinary observations can be evicted; critical events,
settings, identities and fault markers are never cache-overwrite candidates.
Legacy recovery records its eviction count, and old data remain in the verified
external full-flash backups. A completely full legacy filesystem may need one
ordinary record removed before the loss ledger can be written; a power loss
in that narrow recovery window can undercount that single eviction.

The restored storage protection latch is distinguished from current filesystem
health. Recovered storage does not silently authorize heat or clear the saved
fault. The current storage-error buzzer stops when storage is healthy; the
historical latch remains visible and still blocks heating until a safe explicit
operator acknowledgement. Sensor faults still cut power and request an alarm.

The default is 42 C, with a 600-second / 1 C positive-rise protection check and
a +/-1 C thermostat switching band. A valid platform setpoint replaces the
default and persists locally; corrupt saved settings fail closed. Physical
temperature accuracy requires loaded thermal testing, not only software checks.

Ordinary temperature records are an upload cache, not a permanent local archive:
one record per 3600 seconds, deletion after platform acknowledgement, oldest
ordinary-record overwrite when offline/full. Heartbeats still carry current
status and fetch settings. Alarms are not delayed to the hourly record interval.

## Artifact and Automated Checks

- Firmware: `3.2.0-rc8`, monotonic version `32007`.
- Image: 482656 bytes.
- SHA-256: `8b53975de131e1fb15b20daee23009f14a23a955c66a8fab7fe38c22c2add095`.
- RAM: 33000 / 81920 bytes; code: 478499 / 1044464 bytes.
- C++ control (530), UI (34), panel, probe/loop, capacity/eviction, startup and
  catalog/pump checks pass. 95 offline Python tests pass.
- Heater and washer targets compile; only the heater is being flashed.
- Flashing uses one serial session at 115200 baud. A prior protected data-region
  backup can be reused only after its hash and the live device data-region MD5
  match; the current application is read afresh and the reconstructed full backup
  is checked against the live full-flash MD5 before writing. A mismatch falls
  back to reading the full flash. Both application and preserved data are verified.

## Physical Acceptance

The rc8 application-only write completed at 115200 baud with a verified fresh
full-flash backup, matching application hash and unchanged preserved data-region
hash. The firmware subsequently trimmed 56 validated ordinary records during
legacy-cache recovery, retaining 62 queued entries including both critical
events. Configuration and the historical fault latch were retained. The initial
one-time cleanup took about 30 seconds; its warm-up samples were not used for
strict runtime acceptance.

A manual hard reset produced a normal SPI-flash boot. The subsequent 42 status
samples spanned 88.111 seconds of continuously increasing uptime. Every sample
reported one matching externally powered probe with a valid scratchpad, no CRC
error, a valid temperature (25.000-25.125 C), healthy storage/journal/display,
the default 42 C target and the 3600-second observation interval. Probe scans
increased from four to five; the maximum observed loop gap was 111 ms, with no
new loop trip. Heater enable/output and buzzer output remained off throughout.
The protected flash receipt advanced to `verified_running` after the strict
runtime verifier passed. This is controller validation with the load isolated,
not acceptance of heating performance or online delivery.

The restored `storage` latch remains visible and intentionally blocks heating;
it does not indicate a current journal failure. No further ordinary records were
dropped across the hard reset. The heater remains uncommissioned and without
platform/Wi-Fi configuration. No production-server change, washer flash or
protection reset is part of this firmware repair.

Actual network delivery/hourly uploads, buzzer audibility and loaded thermal
performance still require configured-platform and physical-load acceptance.
Real configuration, raw receipts and complete backups remain outside Git or
in ignored artifact storage.
