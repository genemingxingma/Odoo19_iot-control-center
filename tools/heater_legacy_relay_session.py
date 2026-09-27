"""Bounded, explicitly authorized 06458F detection session; no firmware release."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, "D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")


def read_config():
    from run_release import read_config as approved
    return approved()


def connect(*args):
    from run_release import connect as approved
    return approved(*args)


def execute_sudo(*args):
    from run_release import execute_sudo as approved
    return approved(*args)

PRIVATE = Path("D:/Codex/device_backups/heater/legacy-ota-local")
REMOTE = r'''
import json
from datetime import datetime
assert env.cr.dbname == 'odoo-26-1-16'
env.cr.rollback()
env.cr.execute("SET LOCAL statement_timeout = '10s'")
assert env['ir.module.module'].search([('name','=','iot_control_center')]).installed_version == '19.0.2.6.1'
device = env['iot.device'].with_context(lang='en_US').browse(57).exists()
assert len(device) == 1 and device.active and device.company_id.id == 1
assert device._command_identity().upper() == '06458F'
assert device.location_detail == 'Washing Buffer Heater'
assert device.firmware_version == '2.0.2'
if ACTION != 'read':
    env.cr.execute('SELECT id FROM iot_device WHERE id=57 FOR UPDATE NOWAIT')
    device.invalidate_recordset()
    assert device.last_command_id == EXPECTED, 'Concurrent intent changed; stop'
    if ACTION == 'on':
        assert device.last_seen and 0 <= (datetime.utcnow()-device.last_seen).total_seconds() < 90
        assert device.relay_state == 'off' and device.relay_command_state == 'confirmed'
        assert not device.safety_tripped and not device.delay_active
        assert not device.safety_critical and device._max_on_seconds() == 0
        # This temporary device watchdog survives loss of the control connection.
        # The OFF command restores the existing zero timer, without resetting trips.
        device._publish_command('relay', {'state':'on','max_on_sec':360,'maintenance_session':OWNER})
    else:
        assert ACTION == 'off'
        device._publish_command('relay', {'state':'off','max_on_sec':0,'maintenance_session':OWNER})
    env.cr.commit()
    env.invalidate_all()
    device = env['iot.device'].browse(57)
result = dict(device.read(['relay_state','desired_relay_state','relay_command_state',
    'last_command_id','last_command_at','last_command_confirmed_at','last_seen',
    'control_inhibited','safety_tripped','delay_active'])[0])
result['version'] = '19.0.2.6.1'
result['session_owned'] = bool(OWNER) and json.loads(device.last_command_payload or '{}').get('maintenance_session') == OWNER
env.cr.rollback()
print('HEATER_RELAY_SESSION '+json.dumps(result,default=str))
'''


def observer():
    with urllib.request.urlopen("http://192.168.20.200/healthz", timeout=3) as response:
        if response.status != 200 or b"legacy OTA observer" not in response.read(200):
            raise RuntimeError("Observer not ready")
    if (PRIVATE / "release.json").exists():
        raise RuntimeError("Detection requires no firmware release")
    value = json.loads((PRIVATE / "observations.json").read_text(encoding="utf-8-sig"))
    return {d["chip_id"]: {k: d[k] for k in ("chip_id", "requests", "flash_bytes", "free_bytes", "sketch_bytes", "seen_at")}
            for d in value["devices"]}


def remote(client, config, action="read", expected=None, owner=None):
    source = "ACTION=" + repr(action) + "\nEXPECTED=" + repr(expected) + "\nOWNER=" + repr(owner) + "\n" + REMOTE
    encoded = base64.b64encode(source.encode()).decode()
    command = shlex.join(["/opt/odoo/venv/bin/python3", "/opt/odoo/odoo19/odoo-bin", "shell",
        "-c", "/opt/odoo/config/odoo.conf", "-d", "odoo-26-1-16", "--no-http",
        "--max-cron-threads=0", "--logfile=/dev/null"])
    pipeline = "printf %s " + shlex.quote(encoded) + " | base64 -d | " + command
    rc, output = execute_sudo(client, shlex.join(["systemd-run", "--quiet", "--wait", "--pipe", "--collect",
        "-p", "User=odoo", "-p", "IPAddressDeny=any", "-p", "IPAddressAllow=localhost",
        "-p", "IPAddressAllow=192.168.10.20", "-p", "MemoryMax=512M", "-p", "NoNewPrivileges=yes",
        "bash", "-c", pipeline]), config["REMOTE_PASSWORD"], 75)
    line = next((s for s in output.splitlines() if s.startswith("HEATER_RELAY_SESSION ")), None)
    if rc or not line:
        raise RuntimeError("Guarded production action failed; raw startup logs withheld")
    return json.loads(line.split(" ", 1)[1])


def confirmed(client, config, command, state, owner=None):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = remote(client, config, owner=owner)
        if value["last_command_id"] != command:
            raise RuntimeError("Another control intent intervened")
        if value["relay_state"] == state and value["relay_command_state"] == "confirmed":
            return value
        time.sleep(2)
    raise RuntimeError("No device-confirmed switch state within deadline")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-authorized-detection", action="store_true")
    args = parser.parse_args()
    if not args.execute_authorized_detection:
        parser.error("Explicit detection authorization flag required")
    initial_observed = observer()
    if initial_observed:
        print(json.dumps({"status":"already_detected", "devices":list(initial_observed.values())}), flush=True)
        return
    config = read_config()
    client = connect("192.168.10.15", config)
    owned = None
    attempts = []
    owner = uuid.uuid4().hex
    result = {"mode":"detection_only", "relay":"06458F", "firmware_served":False}
    try:
        _, stdout, _ = client.exec_command("hostname")
        assert stdout.read().decode().strip() == "imytestth"
        initial = remote(client, config)
        assert initial["relay_state"] == "off" and initial["relay_command_state"] == "confirmed"
        assert initial["control_inhibited"] and not initial["safety_tripped"]
        expected = initial["last_command_id"]
        for attempt in range(1, 4):
            observer()
            record = {"attempt":attempt}
            attempts.append(record)
            # Set ownership before sending: an SSH transport failure can occur
            # after a committed ON, so cleanup must still inspect and stop it.
            owned = expected
            started = time.monotonic()
            value = remote(client, config, "on", expected, owner)
            owned = value["last_command_id"]
            record["on_command"] = owned
            value = confirmed(client, config, owned, "on", owner)
            record["on_confirmed_seconds"] = round(time.monotonic()-started, 2)
            print(json.dumps({"event":"on_confirmed", **record}), flush=True)
            deadline = time.monotonic()+300
            while time.monotonic() < deadline:
                observed = observer()
                if observed:
                    result["devices"] = list(observed.values())
                    print(json.dumps({"event":"legacy_detected", "devices":result["devices"]}), flush=True)
                    break
                time.sleep(5)
            value = remote(client, config, "off", owned, owner)
            owned = value["last_command_id"]
            value = confirmed(client, config, owned, "off", owner)
            record["off_confirmed"] = True
            expected = owned
            owned = None
            print(json.dumps({"event":"off_confirmed", "attempt":attempt}), flush=True)
            if result.get("devices"):
                break
            print(json.dumps({"event":"no_request", "attempt":attempt}), flush=True)
            if attempt < 3:
                time.sleep(15)
        result["status"] = "detected" if result.get("devices") else "no_device_after_three_attempts"
    finally:
        try:
            if owned:
                current = remote(client, config, owner=owner)
                if not current["session_owned"]:
                    raise RuntimeError("Concurrent intent changed; finite watchdog remains if ON committed")
                if current["relay_state"] != "off" or current["desired_relay_state"] != "off":
                    value = remote(client, config, "off", current["last_command_id"], owner)
                    confirmed(client, config, value["last_command_id"], "off", owner)
            result["final"] = remote(client, config, owner=owner)
        finally:
            result["attempts"] = attempts
            (PRIVATE/"powercycle-session.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            client.close()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
