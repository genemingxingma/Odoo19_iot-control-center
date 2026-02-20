# IoT Control Center (Odoo 19)

Manage ESP8266 relay modules (Wi-Fi + MQTT + OTA).

## Features
- Remote relay ON/OFF control and state reporting.
- Scheduled switching is pushed to device-local storage and continues during network outages.
- Accumulated ON duration statistics (minute precision, displayed as HH:MM).
- Accumulated ON duration reset.
- Firmware upload and batch OTA push.
- Multi-company, multi-department, and multi-location management.
- Temperature/Humidity sensors connected through TCP gateway, with data logging, analysis, trends, and threshold alerts.

## Odoo Dependencies
- Python: `paho-mqtt`, `pytz`

## MQTT Topic Convention
- Odoo -> device command: `{topic_root}/{serial}/command`
- Device -> Odoo status: `{topic_root}/{serial}/status`
- Device -> Odoo telemetry: `{topic_root}/{serial}/telemetry`

## Command Payload
### Relay Control
```json
{"command":"relay","state":"on"}
```
`state` supports `on/off/toggle`.

### Upgrade Command
```json
{"command":"upgrade","url":"https://.../download?...","version":"1.0.2","checksum":"sha256"}
```

### Schedule Push
```json
{
  "command":"schedule_set",
  "version":3,
  "entries":[
    {"weekday":0,"hour":8,"minute":0,"action":"on","offset_min":480},
    {"weekday":0,"hour":20,"minute":0,"action":"off","offset_min":480}
  ]
}
```

### Clear Schedule
```json
{"command":"schedule_clear","version":4}
```

## Temperature/Humidity TCP Report Protocol
The gateway sends line-delimited JSON to Odoo TCP listener (`th_tcp_host:th_tcp_port`):

```json
{
  "gateway_serial": "th-gw-001",
  "token": "optional-secret",
  "reported_at": "2026-02-12T14:00:00Z",
  "probes": [
    {"probe_code": "A1", "temperature": 24.5, "humidity": 56.2},
    {"probe_code": "A2", "temperature": 25.1, "humidity": 58.8}
  ]
}
```

Server behavior:
- Auto-create gateway and probes on first report.
- Store temperature/humidity readings for statistics.
- Open/close temperature/humidity alerts according to sensor thresholds.

## Installation
1. Add `iot_control_center` to Odoo addons path.
2. Install Python dependencies: `pip install paho-mqtt pytz`
3. Update Apps list and install this module.
4. Configure MQTT settings in system settings.
5. Create departments/locations and register devices (`serial` must match firmware).

## Test Preset
- WiFi SSID: `iMyTest_IoT`
- WiFi password: `iMyTest_IoT`
- Odoo 19 CE URL: `http://192.168.10.155:8069`
- Default MQTT host: `192.168.10.155`

Also confirm Odoo system parameter `web.base.url` is `http://192.168.10.155:8069` for OTA download URL generation.
