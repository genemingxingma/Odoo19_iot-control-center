"""Odoo-shell integration probe; refuse all but the named synthetic test DB."""
import json
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from odoo.addons.iot_control_center.services.tcp_service import TCPIngestService

assert env.cr.dbname == "iot_v2_isolated_20260906", "isolated test database only"
suffix = uuid.uuid4().hex
token = secrets.token_hex(32)
gateway = env["iot.th.gateway"].create({"name": "Concurrent ingestion fixture",
    "serial": "concurrency-" + suffix, "company_id": env.company.id, "tcp_token": token})
gateway_id = gateway.id
env.cr.commit()

events = []
for index in range(128):
    payload = {"gateway_serial": gateway.serial, "token": token,
        "node_id": "CONCURRENT", "probes": [{"probe_code": f"CH{channel:02d}",
            "temperature": 22 + index % 3, "humidity": 55} for channel in range(1, 17)]}
    events.append({"protocol_version": 2, "event_id": uuid.uuid4().hex,
        "received_at_ms": int(time.time() * 1000), "payload_text": json.dumps(payload)})

service = TCPIngestService(env.cr.dbname)
started = time.monotonic()
with ThreadPoolExecutor(max_workers=8) as workers:
    first = list(workers.map(service.ingest, events))
    replay = list(workers.map(service.ingest, reversed(events)))
elapsed = time.monotonic() - started
assert all(result["ok"] and result["samples"] == 16 for result in first)
assert all(result["ok"] and result["duplicate"] for result in replay)

changed = dict(events[0], payload_text=events[0]["payload_text"] + " ")
try:
    service.ingest(changed)
except ValueError:
    pass
else:
    raise AssertionError("changed-content replay was accepted")

# Use a new transaction snapshot to observe commits made by concurrent cursors.
env.cr.rollback()
env.invalidate_all()
domain = [("gateway_id", "=", gateway_id)]
assert env["iot.th.reading"].search_count(domain) == 2048
assert env["iot.th.sensor"].search_count(domain) == 16
assert env["iot.ingest.event"].search_count([("event_id", "in", [item["event_id"] for item in events])]) == 128
print("IOT_V2_CONCURRENT_INGEST_OK", json.dumps({"workers": 8, "events": 128,
    "replays": 128, "readings": 2048, "probes": 16, "elapsed_seconds": round(elapsed, 2)}))
env.cr.rollback()
