# IoT Control Center V2 (Odoo 19)

Company-isolated environmental monitoring, relay control, attendance and OpenWrt management.
Production release: Odoo `19.0.2.0.4`, bridge protocol `2`, relay firmware `2.0.2`.

Archived relay identities remain quarantined when retained or late reports arrive. Pending commands are cancelled instead of being dispatched to archived or unbound devices.

**2.0.1 remains quarantined.** Firmware 2.0.2 fixes the retained-schedule stack failure and passed both board-profile canaries. All 11 online relays passed serial upgrade, restoration and bounded fleet observation; two long-offline devices remain archived pending an onsite upgrade. See [the 2.0.2 hardware validation](deploy/RELAY_2_0_2_VALIDATION_2026-09-06.md) and [production acceptance](deploy/PRODUCTION_V2_2026-09-06.md).
The authorized production cutover includes the native HTTP ingestion fixes and an end-migration that converts legacy translated location columns into writable text snapshots. A real queued gateway frame and exact replay were validated against a restored production clone, alongside 70 native Odoo tests.

## Boundaries

- Rust owns MQTT/TCP connections, a durable receipt outbox, HTTP forwarding and bounded OpenWrt probes. Odoo never opens an MQTT/TCP listener.
- A receipt contains `protocol_version`, `event_id`, `received_at_ms` and a typed payload. Persist before forwarding; only the matching successful receipt removes an outbox file.
- Odoo commits receipt identity, raw readings and current probe state together. A repeated identity with different content is rejected.
- Gateways must be registered to a company. Binary gateway source IPs are explicitly mapped to stable gateway identities. JSON gateways require their individual token.
- Probe identity is `(gateway, node, channel)`. Changing company/identity requires a new registration, not automatic reassignment.
- Observations are raw and immutable, with company/location snapshots. Native averages now operate on equal-weight raw samples; no raw/summary mixture exists.
- Retention is company-owned and defaults to zero (no expiry). Positive retention authorizes deletion, not conversion into daily means. Receipts remain for deduplication.
- Relay intent is written to a transactional command outbox before dispatch. Retries retain identity, sequence and expiry; physical state is confirmed separately.
- Country, timezone, internal routes and OTA trust come from company configuration. There are no deployment-specific Wi-Fi credentials, MQTT hosts or OTA URLs compiled into new firmware.

## Operations

Start with **Overview** for company-scoped priorities and four workspaces. The overview never sends relay commands. Device contact, confirmed output state and attendance matching are shown separately. Probe cards show meaningful names, latest values and direct trend links. See [UI and attendance validation](deploy/UI_ATTENDANCE_VALIDATION_2026-09-06.md).

1. Assign viewers `IoT User`, device operators `IoT Operator`, and configuration administrators `IoT Manager`.
2. Configure the company's country, internal WireGuard endpoint, port numbers, retention and trusted OTA certificate fingerprint.
3. Provision a relay with the correct hardware profile and bootstrap network settings. Configured devices expose the setup portal only when the physical button is held at boot.
4. Register each temperature/humidity gateway and its source address or JSON token before sending samples. The bridge retries unregistered gateways rather than guessing ownership.
5. Name probes by equipment/location. Monitoring supports raw/hour/day views; raw requests exceeding 10000 samples explicitly require a narrower range or aggregation.
6. Inspect **Command Delivery** to distinguish queued, published, confirmed and expired commands. A publish is not proof that a relay switched.
7. Mark UV lamps and similar devices safety-critical and configure a finite maximum ON duration. Explicit OFF cancels the delay and inhibits scheduled ON until an explicit new ON/start command. Boot and watchdog cutoff also fail closed.
8. Provision SSH host keys for OpenWrt before probing. Heartbeats have bounded concurrency and SSH deadlines; the bridge no longer silently trusts a new SSH host key.

A gateway may retain its existing public route until its onsite destination has been configured. When switching it to WireGuard, verify the source address actually observed by the bridge and update the existing company's gateway mapping through Odoo. Do not create a second gateway or change probe identities. Confirm fresh readings before retiring public access; do not weaken authentication or compile company endpoints into firmware.

## Bridge Contract

Internal ingestion routes require `X-IoT-Middleware-Token`. A binary event body is:

```json
{
  "protocol_version": 2,
  "event_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "received_at_ms": 1788602400000,
  "source_ip": "192.0.2.10",
  "source_port": 50000,
  "frame_b64": "BASE64_FRAME"
}
```

JSON gateway events carry `payload_text`; MQTT events carry `topic`, `payload`, `retained`.
Successful ingestion returns `ok: true` and the matching `event_id`. Permanent validation failures, including invalid JSON gateway tokens, go to the bridge's rejected directory. Missing gateway registration, database outages and invalid bridge-to-Odoo credentials remain retryable.

`IOT_BRIDGE_QUEUE_PATH` must designate a private, durable V2 directory, not the old JSONL file. Set it explicitly in the protected bridge service configuration. Archive the V1 queue separately; old entries lack trustworthy receipt time and identity and are intentionally not replayed into V2.

The durability boundary starts when persistence succeeds. Device transmissions lost before reaching the bridge, physical power failures before durable write, MQTT QoS 0 delivery and hardware failures are not end-to-end exactly-once guarantees.

## Validation

```text
python -m unittest discover -s core_tests -v
python tools/check_i18n.py
cargo test --locked --offline --manifest-path middleware/iot_bridge/Cargo.toml
python -m platformio run --project-dir firmware/esp8266_relay
python tools/check_relay_stack.py
```

Run Odoo tests with `--test-tags=/iot_control_center` in an isolated database, alternate loopback HTTP ports and `--max-cron-threads=0`. Test mode can bind HTTP despite `--no-http`; never share production ports.

After changing fields or views, run `tools/export_i18n.py` through Odoo shell in the upgraded isolated database, then `python tools/check_i18n.py --write`. Native extraction is required for model references and `odoo-python` / `odoo-javascript` markers. Catalog presence alone is not proof of runtime translation.

See [the multilingual manual](README_MANUAL_zh_en_th.md), [the V2 cutover runbook](deploy/UPGRADE_V2.md) and [isolated validation results](deploy/V2_VALIDATION_2026-09-06.md). No credentials, database dumps or built firmware images belong in Git.
