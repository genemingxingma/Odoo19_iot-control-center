# Fixed Relay Card Layout Acceptance

## Scope

Production **19.0.2.0.8** supersedes the variable-height metadata layout in
19.0.2.0.7. Each card always reserves two lines for location detail and one for
the room, including empty values. Names remain one line; long names/rooms use an
ellipsis and long details are limited to two lines. Full values remain in native
title tooltips and the device form. There is still no Location Detail heading on
the card; the list column is unchanged.

Only view/CSS presentation, tests, a guarded synthetic fixture and documentation
changed. Relay commands, firmware, bridge configuration, company routes and
temperature/humidity ingestion logic were not modified.

## Tests

- Final artifact: 75 native Odoo tests, zero failures/errors; 15 pure protocol
  tests passed; four translation catalogs covering 844 terms passed validation.
- Restored production clone upgraded from 19.0.2.0.7. The preceding snapshot
  migration fix remained effective: untranslated field/metadata, varchar column,
  and actual new reading creation all passed after full native upgrade.
- Actual native Odoo pages were tested in a disposable database through a private
  SSH tunnel with an ephemeral headless Edge profile. Preview/fixture services
  were restricted to loopback and database access; cron and mail delivery were
  disabled. No production sessions or physical relay commands were used.
- Six synthetic cards covered missing detail, missing room, both missing, normal
  metadata, long/multiline metadata and a long device name. All three languages
  (English, Chinese, Thai) passed at 1912, 960 and 390 pixels: nine scenarios,
  covering 54 card layouts. Metadata, state-panel and button offsets differed by
  less than one pixel; there was no document-level horizontal overflow or page
  JavaScript error. Full tooltip values and escaped text were checked.
- Screenshots were visually reviewed and synthetic examples added to the
  English/Chinese/Thai manual. Production operational screenshots were not added
  to the repository.

The first browser trial caught native kanban fields rendering without the usual
widget wrapper. Truncation was moved to the actual containers and the final
artifact was retested; source-template checks alone were not treated as visual
proof. Unavailable optional social integrations queued in the disposable preview
were cancelled there only to prevent repeated native registry reloads.

## Production

The user explicitly authorized publication after tests. Shared laboratory/IoT
release locks, a verified database dump, filestore and source/configuration
backups protected the native upgrade. Only Odoo was stopped; the MQTT broker and
durable bridge stayed running. The pre-restart hashes matched 15 protected
business tables. Contact audit metadata was excluded, but contact business
fields, relay records and current environmental/attendance/clinical history were
preserved. No history discard, V1 rollback or sequence reset was performed.

At 05:48:16 UTC on 2026-09-09, all 50 captured maintenance-queue events had
committed receipts, with no missing events or new rejections. Two newly arrived
events were pending. The latest temperature/humidity reading was 11 seconds old;
no new MQTT processing errors, IoT transaction errors or command records were
found. All four services were active and all 187 artifact files matched deployed
source bytes.

The real production browser showed 11 connected relay cards. Read-only DOM
measurement found **0 pixel difference** between corresponding detail, room,
state-panel and button offsets, including the existing empty metadata card.
No device fields were filled with invented values to achieve alignment.

Tested/deployed artifact SHA-256:
`8587513477c6f975eb74d3d70a08df787d75e4b415a09b0b8def65709ad6f23d`.
Manuals/screenshots and this acceptance note were updated after deployment; they
do not change the tested runtime artifact. These are bounded release checks,
not continuous monitoring or renewed physical-safety certification.
