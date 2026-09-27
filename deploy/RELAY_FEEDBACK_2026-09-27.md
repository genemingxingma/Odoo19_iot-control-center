# Relay feedback release, 2026-09-27

## Outcome

imytestth runs IoT Control Center 19.0.2.6.1. Authenticated MQTT ingress now
processes the audit receipt and state in one transaction, without waiting for
the minute-based cron. Fresh status is persisted before its bounded immediate
forwarding attempt; failed attempts remain in the existing durable outbox.
Duplicate ACKs are idempotent. Repeated telemetry no longer moves an already
confirmed command's timestamp.

Native relay card, list and form views poll every two seconds without overlapping
requests. Hidden tabs, edited records, focused device inputs and open dialogs
suspend polling. The automatically focused search box does not suspend it;
record loading does not replace that input.

## Evidence

- New synthetic rehearsal database: `iot_relay_latency_565f1aa7f99c` on imytestth.
  The actual installed 19.0.2.6.0 addon was installed first, then upgraded.
  All 113 native Odoo tests passed, including immediate HTTP confirmation,
  retained/older reports, receipt replay and company boundaries.
- The Windows bridge passed 12 tests; the Linux bridge passed 14, including its
  two Unix/Linux-specific persistence tests. Both used locked offline dependencies.
- Workspace validation passed 109 Python tests and the JavaScript controller
  harness, including default search autofocus, editing/dialog/visibility guards,
  cadence, non-overlap and unmount cleanup.
- Native Odoo assets compiled in the isolated database, including the final
  search-autofocus refinement. The first asset bundle contained 1398 JS assets.
- Initial tested patch archive SHA-256:
  `82dbe383492c7576020f356ca3bb59b9718ab5527e04908b61c064ab613fd40a`.
- Accepted Linux bridge SHA-256:
  `58614a200013cb89ec2fac847bf1c37c77002ecabfa6249e44e65e610afd44d6`.
- Final refresh JS SHA-256:
  `60bca8d707bced1edfae58f6a7617f907f17f67d65867a3ed36080972972c7f7`.
  This refinement has a separate native asset check, prior-file backup and
  hash-bound frontend receipt. It does not change backend/bridge artifacts.
- Production publication completed at 14:09:34 UTC, followed by the frontend
  refinement. Odoo, bridge and MQTT service health checks passed. Device and
  instrument identity/company registry fingerprints were unchanged.
- Read-only production inspection found new receipts already processed in their
  ingress transaction and no inbound processing backlog. Telemetry still uses
  durable replay; the two-second UI interval is not an end-to-end switch deadline.
- Actual browser checks confirmed visible cards advance their last-contact time
  while the search input retains focus. List and detail navigation also worked.
  Focused form inputs intentionally pause refresh; viewing without editing resumes
  it. These observations are not a physical contact/current test.
- Internal Knowledge articles 1183, 1184 and 1185 received verified Chinese,
  English and Thai feedback instructions. Original article bodies are retained.

## Recovery and Limits

Protected rollback package:
`/opt/odoo/module_backups/iot_relay_latency_publish_565f1aa7f99c/backup`.
It retains the database dump, filestore, addon, bridge binary/configuration,
durable outbox, original guide bodies and pre-refinement JS. Source/file-store
and queue inventories were checked. Full dump decoding is verified without
restoring into production. Shared laboratory/IoT deployment locks were held.

The platform release itself performed no device flashing, relay switching,
protection reset, Wi-Fi configuration or router mutation. The second legacy heater remains detection-only
until load isolation and a reviewed device-specific migration image are ready.
Its private connection details are outside this repository.

## Subsequent Authorized Detection

The user subsequently authorized power-cycling 06458F for legacy heater detection.
Three bounded five-minute connection windows were completed between 14:31 and
14:48 UTC. All ON/OFF intents went through the production command outbox and
received device confirmation. No legacy OTA request was recorded, no image was
served and no release authorization file was created. The observer remains healthy.

Command 18 was created at 14:31:13.387180 UTC; its matching non-retained device
status reached the bridge at 14:31:14.199000 and database ingress at 14:31:14.220992.
This gives approximately 0.812 seconds to the device report and 22 milliseconds
for that report's ingress. It verifies the fast status lane, not load current.
The session tool's longer controller-roundtrip time includes SSH/Odoo startup
and polling; it is not the physical relay actuation time.

Final command 23 confirmed OFF, automatic ON blocked, no safety trip or delay.
The temporary 360-second device watchdog used during each ON window was restored
to the prior zero setting with OFF. Native production list observation also
showed OFF / Confirmed without reloading the page.

Router DNS 192.168.20.1 resolves the old CN OTA host to 192.168.20.200. A local
Wi-Fi scan did not see either original fallback SSID; hidden SSIDs, coverage,
stored EEPROM settings and the other controller's actual firmware are still
unverified. Do not equate absence of a recorded request with proof of a specific
Wi-Fi fault. No router/AP setting was changed.

The fixed PI rc9 candidate and observer/session tools passed 116 local Python
tests, native safety/UI tests, both firmware builds and the JS refresh harness.
They are separate from the already accepted 19.0.2.6.1 production addon; rc9 has
not been flashed or served as a first-generation migration image.
