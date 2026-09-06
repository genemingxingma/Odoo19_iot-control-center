# V2 Cutover Gate

This runbook is preparation, not authorization to deploy to the production database.

## Required Sequence

1. Record exact current Odoo/bridge/firmware versions, gateway identities, source addresses, company ownership, network endpoints and hardware profiles. Export configuration through authorized Odoo access; never put secrets in Git.
2. Back up and verify restoration of the production database, filestore, module source, bridge executable/configuration and firmware inventory. Keep backups in the approved protected location.
3. Validate the complete candidate on a fresh isolated database and a V1-to-V2 upgrade fixture. Disable cron, outgoing integrations and real device commands. Use alternate loopback ports even with Odoo `--no-http` because test mode may bind HTTP.
4. Stop only the affected ingestion paths during the approved cutover window. Archive the V1 JSONL queue. Configure a new private V2 outbox directory; do not feed old messages with fabricated timestamps into V2.
5. Through Odoo ORM set `iot_control_center.v2_discard_monitoring_history` to `true` only after confirming the backup. The standard pre-migration then deletes only module TH history/alerts and removes the obsolete timestamp identity index. Other business history is outside this authorization.
6. Run the standard module upgrade. Register source addresses and company gateways. Review archived inconsistent legacy probes; create new identities where needed instead of forcing cross-company reassignment.
7. Deploy the matching bridge with protected directory permissions and authenticated APIs. Verify invalid events are preserved as rejected, transient errors remain queued, and receipt IDs survive retry/restart. Provision and verify OpenWrt SSH host keys.
8. Provision OTA certificate trust and stage firmware 2.0.0 on a noncritical physical test unit for each supported board profile. Test boot, GPIO polarity, power loss, timer expiry, manual OFF, replay, watchdog and private/public recovery with actual hardware before fleet rollout.
9. Schedule the fleet rollout separately. New firmware must not be assumed tested on every relay merely because a shared build succeeds. Verify device-reported version, configuration revision and actual electrical state.

## Rollback

Before hardware rollout, restore the verified V1 database/filestore/code backup as a matched set. A code-only downgrade is invalid because V2 discards mixed-granularity history and changes identities.

After a device is on V2, account for monotonic command sequences and the inhibit latch. A database restore must not restart command numbering below the device's last accepted sequence. Restore command history/sequence state or reprovision the device under a controlled procedure. Do not reset sequence state by automatically accepting arbitrary old commands.

## Explicit Limits

- V1 readings and summary rows are not migrated. Full preservation was explicitly deprioritized in favor of the new architecture.
- Event receipts are retained to prevent replay after raw-history expiry; capacity/backup planning must include this index.
- There is no claim of exactly-once physical actuation, hardware certification or safe UV operation without physical interlocks and on-site validation.
- MQTT bootstrap/broker authentication and network segmentation remain deployment responsibilities. OTA certificate trust must be pinned by an administrator, not auto-learned from an untrusted connection.
- `tools/test_on_imytestth.sh` targets only `iot_v2_isolated_20260906` under a separate source/filestore path. It never restarts production services.
