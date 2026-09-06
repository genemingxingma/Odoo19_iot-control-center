# V2 Cutover Gate

This runbook is preparation. Deployment authorization remains conditional on every release gate passing.

For the completed authorized deployment, see [production acceptance](PRODUCTION_V2_2026-09-06.md).
V1 upgrades must include the 19.0.2.0.4 end-migration for the legacy JSON location
snapshot column and a real gateway-frame write/replay check after the complete
upgrade, not only an empty-history or standalone conversion test.

V1 firmware is not compatible with V2 control semantics. In particular, 1.8.x does not implement `delay_start`, command expiry or monotonic command sequences. Do not deploy the backend alone and leave 1.8.x devices operating under it, or assume that a successful MQTT publish proves compatibility.

## Firmware and Backend Gates

The initial 2026-09-06 2.0.1 rolling-migration trial stopped after the IoT-Outlet canary repeatedly reconnected. Record 15 remains quarantined. Firmware 2.0.2 fixes the retained-schedule/report stack path and passed both board-profile canaries; see `RELAY_2_0_2_VALIDATION_2026-09-06.md` for the separate serial rollout. This does not clear the V2 database/bridge cutover gates below. The original incident remains in `CANARY_V2_2026-09-06.md`.

The candidate has a one-way V1 migration mode loaded only from an existing V1 state file. A valid sequenced V2 command permanently closes that mode. Fresh devices remain strict V2. Migration mode does not add missing sequence/expiry fields to V1 traffic and only deduplicates identified V1 commands within a 16-entry receipt cache. Unidentified legacy commands retain V1 behavior. This compatibility path is not evidence that the physical hardware release gates have passed.

## Required Sequence

1. Record exact current Odoo/bridge/firmware versions, gateway identities, source addresses, company ownership, network endpoints and hardware profiles. `tools/v2_release_preflight.py` is a read-only Odoo-shell inventory; it does not authorize a release. Resolve duplicate gateway identities, unowned active gateways and inconsistent active probe ownership through reviewed V1 ORM operations before upgrading. Never infer every company's ownership from a default company or changing public IP. Export configuration through authorized Odoo access; never put secrets in Git.
2. Back up and verify restoration of the production database, filestore, module source, bridge executable/configuration and firmware inventory. Keep backups in the approved protected location.
3. Validate the complete candidate on a fresh isolated database and a V1-to-V2 upgrade fixture. Disable cron, outgoing integrations and real device commands. Use alternate loopback ports even with Odoo `--no-http` because test mode may bind HTTP. Provision a noncritical physical unit for each board profile against an isolated V2 controller/broker, and validate GPIO polarity, boot/power loss, timer expiry, OFF, replay, watchdog and private/public recovery before any production cutover.
4. Plan a coordinated backend/bridge/firmware maintenance window with device operators. Verify safe physical output states and isolate hazardous loads; software-reported OFF is not proof of electrical isolation. Do not leave incompatible or unreachable units under the V2 controller. Stop only the affected ingestion paths. Archive the V1 JSONL queue. Configure a new private V2 outbox directory; do not feed old messages with fabricated timestamps into V2.
5. Through Odoo ORM set `iot_control_center.v2_discard_monitoring_history` to `true` only after confirming the backup. The standard pre-migration then deletes only module TH history/alerts and removes the obsolete timestamp identity index. Other business history is outside this authorization.
6. Run the standard module upgrade. The migration checks gateway identities and ownership before deleting history; it refuses inconsistent active probes instead of silently archiving them. Register the reviewed stable source addresses or JSON gateway credentials before resuming ingestion. Preserve meaningful probe names and locations; use new identities when a genuine company transfer requires them.
7. Deploy the matching bridge with protected directory permissions and authenticated APIs. Verify invalid events are preserved as rejected, transient errors remain queued, and receipt IDs survive retry/restart. Provision and verify OpenWrt SSH host keys.
8. Provision the already validated OTA certificate trust and deploy the tested firmware/controller pair within the coordinated window. A 2.x firmware must not be assumed tested on every relay merely because a shared build succeeds. Resolve any candidate quarantine first through a new verified hardware trial, not by bypassing the wizard guard.
9. Verify each device-reported version, configuration revision and actual electrical state before re-enabling its load or schedules. Keep inaccessible or unverified equipment isolated; report remaining units explicitly rather than claiming full fleet completion.

## Rollback

Before hardware rollout, restore the verified V1 database/filestore/code backup as a matched set. A code-only downgrade is invalid because V2 discards mixed-granularity history and changes identities.

After a device is on V2, account for monotonic command sequences and the inhibit latch. A database restore must not restart command numbering below the device's last accepted sequence. Restore command history/sequence state or reprovision the device under a controlled procedure. Do not reset sequence state by automatically accepting arbitrary old commands.

## Explicit Limits

- V1 readings and summary rows are not migrated. Full preservation was explicitly deprioritized in favor of the new architecture.
- Event receipts are retained to prevent replay after raw-history expiry; capacity/backup planning must include this index.
- There is no claim of exactly-once physical actuation, hardware certification or safe UV operation without physical interlocks and on-site validation.
- MQTT bootstrap/broker authentication and network segmentation remain deployment responsibilities. OTA certificate trust must be pinned by an administrator, not auto-learned from an untrusted connection.
- `tools/test_on_imytestth.sh` targets only `iot_v2_isolated_20260906` under a separate source/filestore path. It never restarts production services.
