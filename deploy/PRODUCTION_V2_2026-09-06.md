# Production V2 Acceptance

## Released Scope

The authorized production deployment runs Odoo module **19.0.2.0.4**, bridge
protocol **2**, and the previously validated relay firmware **2.0.2**.
The backend, bridge, operations overview, named probe cards/trends, relay command
outbox and attendance ingestion changes are deployed. No firmware was flashed
or relay output switched during this backend release.

- Exact tested module archive SHA-256: `e8ad61bf27da8af0aaa2add37f9cb9a9afee360942b04ad5b48ff3c6c967ac49`.
- Deployed Linux bridge SHA-256: `8c82270ae49dcfc7e1c922f03bd838a1bbcd304b172f83b98ae2a7d45065b066`.
- Runtime source is the tested archive; subsequent README/manual changes document acceptance only.
- Acceptance snapshot: 2026-09-06 16:54:55 UTC.

## Verification

- 70 native Odoo tests passed with zero failures/errors, including real HTTP
  ingestion, token rejection, bounded request bodies, transaction rollback,
  replay and archived-device quarantine.
- 15 independent protocol/core tests passed. Four translation catalogs passed
  the 844-source-term check. Python compilation and Git whitespace checks passed.
- A restored production database and filestore were used for native migration
  testing with cron disabled and outbound networking restricted.
- A real queued binary gateway frame created two readings in the clone.
  Replaying the exact envelope returned a duplicate receipt without extra rows.
- All 16 original, company-bound probes received new production observations
  after the repair. No duplicate `(sensor, event)` rows were found. The durable
  bridge outbox drained; no rejected events were present at acceptance.
- Both hardware profiles passed correlated V2 configuration handshakes, then
  the remaining relays were checked serially. All 11 online relays returned the
  expected command ID, monotonic sequence and configuration revision; the backend
  marked all 11 commands confirmed. Fresh fleet observation matched the previous
  OFF state, timer/inhibit state, schedule count and maximum ON duration.
- All registered relays, probes, the attendance terminal and both access points
  had recent contact at the acceptance snapshot. Retained MQTT discoveries without
  a company remain unassigned and received no commands; they are not counted as
  registered company devices.
- Production browser checks rendered the overview, named probe cards and named
  trend legend. Existing synthetic desktop/mobile screenshots remain in the manual;
  production screenshots and private records were not added to Git.
- Employee, raw punch, HR attendance, probe configuration and clinical records
  were hash-checked across maintenance. Contact business content was preserved;
  standard group updates touched contact `write_date` metadata only.

## Issues Caught During Release

The first maintenance attempt stopped on a service-account evidence-directory
permission check. The matched backup was restored before a device entered V2
control mode. Permissions and a pre-stop service-account read check were corrected.

Real production ingestion exposed an inherited V1 translated location column
still stored as JSONB. The V2 field is an immutable plain-text snapshot. Version
19.0.2.0.4 explicitly converts and verifies the actual column at the end of native
module migration, retaining an English or available fallback label. A standalone
conversion test was insufficient; the final gate also tested a real frame after
the complete cloned-database upgrade. Durable production events were retried with
their original IDs and reception times, not fabricated backfill timestamps.

One release-only Odoo-shell handshake encountered a serialization conflict after
waiting for MQTT while holding an old transaction snapshot. It rolled back before
publication. The diagnostic script now starts a fresh, short, row-locked transaction
after observation. All subsequent handshakes completed, with no sequence reset.

## Operational Boundaries

- The existing temperature/humidity public route is intentionally retained at
  the owner's request. The onsite gateway/router configuration was not changed.
  After onsite destination configuration, verify the WireGuard source seen by the
  bridge, update the existing company's gateway mapping through Odoo, and prove
  fresh samples before retiring public access. No company endpoint is compiled
  into firmware.
- Two long-offline 1.8.8 relay identities remain archived and require an onsite
  upgrade and validation before reactivation. They were not reported as upgraded.
- Historical attendance exceptions still require review; recent terminal contact
  is not proof that every historical HR entry or physical punch flow is correct.
  No historical attendance recalculation or terminal clearing was performed.
- Environmental threshold alerts remain visible. Release acceptance verifies
  ingestion and display, not the correctness of physical probe placement, equipment
  temperatures or thresholds. Those require operational review.
- Only the expressly authorized old environmental observations/alerts were reset.
  The original data remains in protected backups. No preservation claim is made
  for gateway transmissions that did not reach the durable bridge during downtime.
- After a valid V2 command, a relay permanently rejects V1 commands. Do not restore
  the pre-cutover controller database or reset command sequences as a casual
  rollback. Keep matched V2 backups and plan any recovery with device state in view.

Database, filestore, module, bridge configuration, durable queue and private
verification evidence are backed up on the production host. Credentials, dumps,
raw attendance data and retained command payloads are not in this repository.
