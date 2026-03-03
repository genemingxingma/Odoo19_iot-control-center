# iot_bridge (Rust Middleware)

Decoupled IoT middleware for Odoo IoT Control Center.

## What it does

- Subscribes MQTT: `iot/relay/+/status`, `iot/relay/+/telemetry`
- Forwards MQTT payloads to Odoo internal ingest API
- Listens TH TCP packets (JSON line + binary frame `FA CE ...`)
- Forwards TH frames to Odoo internal ingest API
- Exposes command API for Odoo:
  - `POST /v1/switch/{serial}/command`

## Why

This keeps MQTT/TCP real-time traffic out of Odoo workers and reduces lock/contention impact.

## Build

```bash
cd middleware/iot_bridge
cargo build --release
```

## Run

```bash
cd middleware/iot_bridge
set -a; source .env.example; set +a
cargo run --release
```

## API

### Health

`POST /healthz`

### Publish switch command

`POST /v1/switch/{serial}/command`

Body:

```json
{
  "command": "relay",
  "payload": { "state": "on" },
  "retain": false
}
```

The middleware publishes to MQTT topic:

`{MQTT_TOPIC_ROOT}/{serial}/command`

with merged JSON payload:

```json
{"command":"relay","state":"on"}
```

## Odoo side config

In Odoo Settings -> IoT Control Center:

- Enable `Use External Middleware`
- Set `Middleware Base URL` (example: `http://127.0.0.1:8099`)
- Set `Middleware Token` (must match `IOT_BRIDGE_TOKEN`)

When enabled, Odoo command publishing goes to middleware API.
Incoming MQTT/TH data should be forwarded by middleware to:

- `/iot_control_center/internal/mqtt_ingest`
- `/iot_control_center/internal/th_ingest_json`
- `/iot_control_center/internal/th_ingest_binary`
