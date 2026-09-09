# Relay Detail Production Acceptance

## Released Scope

Production module **19.0.2.0.7** was accepted on 2026-09-09. The relay card shows
the existing location detail without a field heading; the list keeps the column
beside the device name. Blank card details are omitted and text wraps.

The release also permanently retires legacy translation metadata for the
immutable temperature/humidity location snapshot. Device location fields remain
translatable. No bridge, firmware, relay-control or gateway-routing changes were
made. The existing public temperature/humidity gateway route remains in place.

## Upgrade Finding And Correction

The initial 19.0.2.0.5 native upgrade passed fresh-database tests but failed the
protected-record comparison before production was reopened: the legacy location
snapshot column reverted from varchar to JSONB. All existing reading values were
still present as English JSON entries, but the runtime expected plain text.

Odoo 19 loads `ir.model.fields.translate` into
`registry._database_translated_fields` before module pre-migrations. Its model
setup uses that cache to preserve translated columns even when the source
explicitly declares `translate=False`. A column-only end-migration does not retire
this metadata. The 19.0.2.0.6 declaration-only candidate was rejected in the
production clone and was not deployed to production.

The 19.0.2.0.7 pre-migration converts the existing snapshot to text, preserves an
English or existing-language fallback value, clears only this field's persisted
translation marker, and removes only this field from the native upgrade cache.
No Odoo core source was changed. The regression also checks that other translated
fields retain their metadata and that the migration is idempotent.

## Verification

- 74 native Odoo tests: zero failures and zero errors.
- 15 pure Python protocol tests passed; four catalogs covering 844 terms passed
  validation. Python compilation and Git whitespace checks passed.
- Restored production clone: two consecutive complete native upgrades both left
  the registry field and metadata untranslated, the column varchar, and actual
  snapshot creation writable. The second upgrade does not rerun the migration.
- An actual gateway frame with an isolated new event identity created two
  readings; repeating the same event was recognized as a duplicate. This was a
  clone-only replay, not a physical-device test or fabricated production sample.
- Production native views and field labels passed English, Chinese and Thai
  checks. Production Edge screenshots confirmed the card has no heading and the
  list has a visible Location Detail column. Long existing text and an empty
  detail were both checked. Screenshots contained operational data and were not
  published into this repository. This release's live visual check was desktop;
  language checks for Chinese and Thai were native ORM checks, not browser tests.

## Protection And Live Readback

A protected database dump, filestore, module source and configuration backup was
completed before the first upgrade. The dump was parsed by `pg_restore` and its
SHA-256 checked again before the corrective upgrade. Release locks covered both
the laboratory and IoT deployment paths. No credentials or backups are in Git.

Odoo was unavailable for approximately 24 minutes while the migration issue was
diagnosed and tested. MQTT and the durable bridge outbox remained running. There
was no public restart with the incompatible snapshot column and no database
rollback after production reopened at approximately 05:04 UTC.

The pre-restart comparison matched 15 protected tables, including all 18,734
existing readings, device records, employee/attendance and clinical records.
Only contact update metadata (`write_date` and `write_uid`) was excluded after
full-row comparison against the verified backup proved every business field was
unchanged. No historical readings were discarded in this release.

At 05:05:34 UTC, all 583 captured maintenance-queue event IDs had committed
receipts, with no missing durable events. One new event was pending at the
snapshot. Existing rejected invalid zero-pair frames remained quarantined;
there were no new rejected events in this observation. The latest reading was
27 seconds old and no new MQTT processing or IoT transaction errors were found.
All 185 files in the tested artifact matched production source bytes.

The closing readback at 05:11:46 UTC still showed all captured receipts present
and zero new IoT transaction/MQTT processing errors. Two additional rejected
frames were diagnosed by the unchanged decoder as invalid temperature/humidity
zero-pairs, bringing the quarantined total to 29. These incoming data-quality
exceptions were retained, not deleted or relabeled as successful readings.

Native readback and refreshed cards confirmed all 11 active relays had recent
contact. No new command records were created during the release. Ten devices
had location details; one existing blank was intentionally not guessed or filled.
The two previously archived old-firmware devices remain outside this release.

Tested and deployed artifact SHA-256:
`53bbc6246fd16284f2c80eca149f3dbfc4d89546b95200c7d0a74497456ad216`.
Release documentation was updated after runtime acceptance and does not change
the tested executable artifact. These are bounded release checks, not a claim
of continuous monitoring or physical/electrical safety validation.
