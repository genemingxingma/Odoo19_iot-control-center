# UI and Attendance Candidate Validation

Date: 2026-09-06 (Asia/Bangkok). Candidate: Odoo `19.0.2.0.1`.

## Scope and Deployment Boundary

This work changes the V2 candidate UI and attendance ingestion/matching. Relay firmware and bridge binaries are unchanged. It is not a production backend cutover or a repair of historical HR records.

Read-only production checks observed one ADMS terminal with recent contact and 1028 punch records earlier in this task. The latest SSH service check found `odoo.service` active. These facts do not establish that all punches matched correctly. No production punch distribution, employee records or raw biometric payloads were exported. Privileged production paths were not accessible in the current non-interactive SSH session.

The previous V2 cutover gates still apply: protected backup and restore verification, company/gateway ownership audit, explicit environmental-history migration policy and coordinated bridge/backend compatibility. See [UPGRADE_V2.md](UPGRADE_V2.md). Do not deploy this branch as a UI-only hotfix on a V1 database.

## Confirmed Code Defects and Corrections

| Area | Finding | Candidate behavior |
| --- | --- | --- |
| ADMS parser | Verification method was used as the in/out direction. | Parse positional STATUS separately from VERIFY; preserve empty columns and PIN zero. |
| Batch processing | Upload order could mispair check-in/out; one HR validation error could discard unrelated punches. | Sort before matching; keep individual business errors reviewable in savepoints. Database errors still fail the batch. |
| Upload acknowledgement | Failed ingestion could return a successful `OK`. | Roll back failed batches and return non-success status/body. Replays are deduplicated. |
| Odoo 19 HTTP | Catching write errors can interfere with read-only transaction fallback; raw request APIs differ. | Explicit `readonly=False`; use the supported bounded `get_data()` API. Real HTTP tests cover dispatch. |
| Company identity | Employee fallback could cross companies; conflicting serials could match a shared address. | Company-scoped unambiguous employee lookup; mapping constraint; serial mismatch never falls back to VPN/NAT IP. |
| Device data | Pull synchronization could clear terminal logs before commit. | Never clear terminal logs during synchronization, even if the former checkbox is stored as enabled. |
| Network URLs | Internal port settings could be ignored; HTTPS could be invented on an HTTP-only port. | Use company HTTP endpoint; show HTTPS only for a configured TLS base URL. |
| Translation | Catalog strings could lack runtime references/comments. | Native Odoo extraction, reviewed Chinese/Thai wording and runtime language assertions. |

Protocol basis: the [ZKTeco-authored PUSH protocol manual (mirrored copy)](https://studylib.net/doc/27718586/ilide.info-attendance-push-communication-protocol-2020032...) distinguishes attendance status from verification mode. The [pyzk record model](https://github.com/fananimi/pyzk/blob/master/zk/attendance.py) likewise keeps `status` and `punch` separate. These sources support parser corrections, not a claim that the installed terminal's entire protocol has been certified.

## UI Changes

- A company-scoped Overview prioritizes pending attendance, offline devices, silent probes and open alerts. Metric links use matching domains. Refresh failure leaves an explicit stale-data warning rather than silently showing cached values as current.
- Named probe cards show current values, sample age and trend links; technical identifiers remain available. Relay cards separate confirmed state from requested state and pending commands.
- Attendance lists/forms separate terminal contact from HR processing, display review counts and link to filtered punch records. New punches and errors are searchable; technical fields are optional or moved to details.
- All styles are module-scoped. Overview layouts were checked at 1440px desktop and 390px mobile widths, in Chinese, Thai and English. Reduced-motion support and visible keyboard focus are included.

## Verification

Environment: local Docker Odoo `19.0-20260817`, PostgreSQL 16.14, disposable database `iot_ui_test_20260906`. Synthetic records only. PostgreSQL has no published port. HTTP preview is bound to Windows loopback `127.0.0.1:18169`; a temporary preview-only helper is excluded from Git and disabled by stopping the preview container. No actual relay commands were issued.

At close-out the preview and disposable database containers were stopped, and the temporary preview helper source was removed. No preview authentication helper is included in this release.

- Independent Python core tests: 15 passed.
- Odoo model and actual HTTP tests: 61 passed, zero failures/errors. Includes reordered batches, replay, empty columns, photo-table exclusion, cross-company mappings, overlapping HR data, invalid/oversized uploads, denied sources, unknown serials, consumed form bodies, and overview count/action consistency.
- Translation validation: four catalogs, native runtime markers, matching placeholders. Chinese and Thai model labels, overview messages and stored sync-summary display were verified at runtime.
- Browser checks: all four workspaces render, named-probe trend opens, attendance priority and per-device review links return the expected synthetic record, connected-relay count opens only connected records, refresh failure is visible and recovers on retry. No JavaScript errors in final normal navigation; the intentionally aborted refresh produces the expected network error.
- Layout checks: no overview horizontal overflow at 390px; single-column cards on mobile. Screenshots were visually reviewed.

Screenshots: [Chinese overview](../docs/screenshots/overview-zh-desktop.png), [Thai overview](../docs/screenshots/overview-th-desktop.png), [English overview](../docs/screenshots/overview-en-desktop.png), [probe cards](../docs/screenshots/probes-zh-desktop.png), [attendance review](../docs/screenshots/attendance-form-zh-desktop.png), [relay cards](../docs/screenshots/relays-zh-desktop.png), [Chinese mobile](../docs/screenshots/overview-zh-mobile.png), [Thai mobile](../docs/screenshots/overview-th-mobile.png).

## Remaining Acceptance Work

Do not automatically recalculate historical attendance: earlier misclassified punches, open shifts and employee mappings need a separate reviewed repair policy. The isolated results do not quantify production historical damage.

Device-specific ADMS initialization, `OK` versus count-bearing acknowledgements, clock synchronization, retry behavior and late uploads across multiple batches still require observation on the actual terminal. The existing successful-response form remains unchanged; this patch changes failure acknowledgement. Concurrent hardware delivery and network recovery are not certified by these functional tests. Continue to restrict unauthenticated legacy ADMS reception to approved VPN/source addresses; serial numbers are identifiers, not authentication secrets.
