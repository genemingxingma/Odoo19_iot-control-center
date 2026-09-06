# IoT Control Center V2 (Odoo 19)

Company-isolated environmental monitoring, relay control, attendance and OpenWrt management.
This is a breaking architecture release: Odoo `19.0.2.0.0`, bridge protocol `2`, relay firmware `2.0.0`.
The candidate is for isolated validation, not permission to upgrade a production database or real devices.

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

1. Assign viewers `IoT User`, device operators `IoT Operator`, and configuration administrators `IoT Manager`.
2. Configure the company's country, internal WireGuard endpoint, port numbers, retention and trusted OTA certificate fingerprint.
3. Provision a relay with the correct hardware profile and bootstrap network settings. Configured devices expose the setup portal only when the physical button is held at boot.
4. Register each temperature/humidity gateway and its source address or JSON token before sending samples. The bridge retries unregistered gateways rather than guessing ownership.
5. Name probes by equipment/location. Monitoring supports raw/hour/day views; raw requests exceeding 10000 samples explicitly require a narrower range or aggregation.
6. Inspect **Command Delivery** to distinguish queued, published, confirmed and expired commands. A publish is not proof that a relay switched.
7. Mark UV lamps and similar devices safety-critical and configure a finite maximum ON duration. Explicit OFF cancels the delay and inhibits scheduled ON until an explicit new ON/start command. Boot and watchdog cutoff also fail closed.
8. Provision SSH host keys for OpenWrt before probing. Heartbeats have bounded concurrency and SSH deadlines; the bridge no longer silently trusts a new SSH host key.

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
```

Run Odoo tests with `--test-tags=/iot_control_center` in an isolated database, alternate loopback HTTP ports and `--max-cron-threads=0`. Test mode can bind HTTP despite `--no-http`; never share production ports.

See [the multilingual manual](README_MANUAL_zh_en_th.md), [the V2 cutover runbook](deploy/UPGRADE_V2.md) and [isolated validation results](deploy/V2_VALIDATION_2026-09-06.md). No credentials, database dumps or built firmware images belong in Git.
