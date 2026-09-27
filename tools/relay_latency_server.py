"""Synthetic upgrade rehearsal and hash-bound, backed-up latency-only release."""
import ast
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tarfile
import time

assert os.geteuid() == 0
assert subprocess.check_output(["hostname"], text=True).strip() == "imytestth"
mode, stage = sys.argv[1], Path(sys.argv[2])
assert mode in ("test", "publish")
assert stage.parent == Path("/home/mamingxing") and stage.name.startswith("iot-relay-latency-")
os.umask(0o077)
metadata = json.loads((stage / "package.json").read_text())
assert metadata["version"] == "19.0.2.6.1"
for name, key in (("patch.tgz", "patch_sha256"), ("bridge.tgz", "bridge_source_sha256")):
    assert hashlib.sha256((stage / name).read_bytes()).hexdigest() == metadata[key]
live = Path("/opt/odoo/custom_addons/iot_control_center")
user = pwd.getpwnam("odoo")
settings = configparser.ConfigParser(interpolation=None)
settings.read("/opt/odoo/config/odoo.conf")
options = settings["options"]
assert options.get("db_name") == "odoo-26-1-16" and options.get("db_host") == "192.168.10.20"
pg = os.environ.copy()
pg["PGPASSWORD"] = options["db_password"]
pgargs = ["-h", options["db_host"], "-p", options.get("db_port", "5432"), "-U", options["db_user"]]
root = Path("/tmp" if mode == "test" else "/opt/odoo/module_backups") / ("iot_relay_latency_" + mode + "_" + stage.name[-12:])
root.mkdir(mode=0o750, exist_ok=mode == "publish")
os.chown(root, 0, user.pw_gid)
os.chmod(root, 0o750)


def emit(label, body):
    print(label, json.dumps(body, default=str), flush=True)


def inventory(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def run(args, label, env=None, timeout=1800):
    with (root / (label + ".log")).open("wb") as log:
        result = subprocess.run(args, stdout=log, stderr=log, env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Failed phase " + label + "; inspect its protected log")
    emit("PHASE_OK", {"phase": label})


def isolated(args, label, timeout=1800):
    run(["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "-p", "User=odoo",
         "-p", "IPAddressDeny=any", "-p", "IPAddressAllow=localhost", "-p", "IPAddressAllow=192.168.10.20",
         "-p", "NoNewPrivileges=yes", "-p", "MemoryMax=3G", "-p", "RuntimeMaxSec=" + str(timeout),
         *args], label, timeout=timeout + 30)


def odoo_flags(db, conf, addons, data):
    assert db != "odoo-26-1-16" or mode == "publish"
    return ["/opt/odoo/venv/bin/python3", "/opt/odoo/odoo19/odoo-bin", "-c", str(conf),
            "-d", db, "--db-filter=^" + db + "$", "--addons-path=" + str(addons) + ",/opt/odoo/odoo19/odoo/addons",
            "--data-dir=" + str(data), "--workers=0", "--max-cron-threads=0"]


def sql_fingerprint(db):
    query = """SELECT 'iot_device|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,serial,module_id,company_id,active)),'' ORDER BY id),'')) FROM iot_device;
SELECT 'iot_instrument|'||count(*)||'|'||md5(coalesce(string_agg(md5(concat_ws('|',id,name,uid,company_id,active,token_hash)),'' ORDER BY id),'')) FROM iot_instrument;"""
    return subprocess.check_output(["psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", *pgargs, "-d", db, "-c", query], env=pg)


if mode == "test":
    assert ast.literal_eval((live / "__manifest__.py").read_text())["version"] == "19.0.2.6.0"
    for name, expected in metadata["baseline"].items():
        source = live / name
        assert (not source.exists()) if expected is None else hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected, "Live file differs from reviewed baseline: " + name
    before = inventory(live)
    old, candidate = root / "old/iot_control_center", root / "candidate/iot_control_center"
    shutil.copytree(live, old, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(old, candidate)
    with tarfile.open(stage / "patch.tgz") as archive:
        archive.extractall(candidate, filter="data")
    for name, digest in metadata["files"].items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == digest
    for folder in (old.parent, candidate.parent):
        shutil.chown(folder, user="odoo", group="odoo")
        os.chmod(folder, 0o750)
    run(["chown", "-R", "odoo:odoo", str(old), str(candidate)], "test-source-owner")
    data = root / "data"
    data.mkdir(mode=0o700)
    shutil.chown(data, user="odoo", group="odoo")
    conf = root / "test.conf"
    test = configparser.ConfigParser(interpolation=None)
    test["options"] = {k: v for k, v in options.items() if k in ("db_host", "db_port", "db_user", "db_password", "db_sslmode")}
    db = "iot_relay_latency_" + stage.name[-12:]
    test["options"].update({"db_name": db, "dbfilter": "^" + db + "$", "smtp_server": "127.0.0.1", "smtp_port": "9",
        "http_interface": "127.0.0.1", "http_port": "18869", "gevent_port": "18872", "list_db": "False",
        "logfile": str(root / "native.log"), "server_wide_modules": "base,web"})
    with conf.open("w") as file:
        test.write(file)
    shutil.chown(conf, user="odoo", group="odoo")
    (root / "native.log").touch()
    shutil.chown(root / "native.log", user="odoo", group="odoo")
    isolated(odoo_flags(db, conf, old.parent, data) + ["-i", "iot_control_center", "--without-demo=all", "--stop-after-init", "--no-http"], "install-installed-version")
    isolated(odoo_flags(db, conf, candidate.parent, data) + ["-u", "iot_control_center", "--test-enable", "--test-tags=/iot_control_center", "--stop-after-init"], "upgrade-and-native-tests")
    log = (root / "native.log").read_text()
    import re
    assert not re.search(r"[1-9][0-9]* failures|[1-9][0-9]* errors|At least one test failed", log)
    assert "post-tests" in log and "0 failed" in log
    bridge = root / "bridge"
    bridge.mkdir()
    with tarfile.open(stage / "bridge.tgz") as archive:
        archive.extractall(bridge, filter="data")
    cargo_env = os.environ.copy()
    cargo_env["CARGO_HOME"] = "/home/mamingxing/.cargo"
    cargo_env["RUSTUP_HOME"] = "/home/mamingxing/.rustup"
    cargo_env["PATH"] = "/home/mamingxing/.cargo/bin:" + cargo_env["PATH"]
    cargo_env["CARGO_TARGET_DIR"] = "/home/mamingxing/iot-relay-latency-build-cache"
    for phase, flags in (("bridge-tests", ["test"]), ("bridge-build", ["build", "--release"])):
        run(["/home/mamingxing/.cargo/bin/cargo", *flags, "--manifest-path", str(bridge / "Cargo.toml"),
             "--locked", "--offline", "-j", "2"], phase, env=cargo_env)
    bridge_log = (root / "bridge-tests.log").read_text()
    bridge_result = re.search(r"test result: ok\. (\d+) passed; 0 failed", bridge_log)
    assert bridge_result and int(bridge_result[1]) >= 12
    binary = root / "iot_bridge"
    shutil.copy2(Path(cargo_env["CARGO_TARGET_DIR"]) / "release/iot_bridge", binary)
    result = {"status": "passed", "host": "imytestth", "database": db, "root": str(root),
        "patch_sha256": metadata["patch_sha256"], "candidate": str(candidate), "candidate_inventory": inventory(candidate),
        "installed_inventory": before, "bridge_binary": str(binary), "bridge_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "old_bridge_sha256": hashlib.sha256(Path("/usr/local/bin/iot_bridge").read_bytes()).hexdigest(),
        "bridge_source_sha256": metadata["bridge_source_sha256"], "bridge_tests": int(bridge_result[1])}
    (stage / "test-receipt.json").write_text(json.dumps(result))
    emit("RELAY_LATENCY_TEST_PASSED", {k:v for k,v in result.items() if not k.endswith("inventory")})
else:
    locks = []
    for name in ("imytestth-laboratory-release", "imytestth-iot-release"):
        lock = open("/run/lock/" + name + ".lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(lock)
    accepted = json.loads((stage / "test-receipt.json").read_text())
    assert accepted["status"] == "passed" and accepted["host"] == "imytestth"
    assert accepted["patch_sha256"] == metadata["patch_sha256"]
    assert accepted["bridge_source_sha256"] == metadata["bridge_source_sha256"]
    candidate = Path(accepted["candidate"])
    assert inventory(live) == accepted["installed_inventory"], "Live addon changed after rehearsal"
    assert inventory(candidate) == accepted["candidate_inventory"]
    binary = Path(accepted["bridge_binary"])
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == accepted["bridge_sha256"]
    assert hashlib.sha256(Path("/usr/local/bin/iot_bridge").read_bytes()).hexdigest() == accepted["old_bridge_sha256"]
    assert shutil.disk_usage(root).free > 8 * 1024**3
    for service in ("odoo", "iot-bridge", "mosquitto"):
        assert subprocess.check_output(["systemctl", "is-active", service], text=True).strip() == "active"
    bridge_env = {}
    for line in Path("/etc/iot_bridge.env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            bridge_env[k.strip()] = v.strip().strip('"').strip("'")
    assert "IOT_BRIDGE_QUEUE_PATH" in bridge_env, "Durable outbox must be explicitly configured"
    queue = Path(bridge_env["IOT_BRIDGE_QUEUE_PATH"])
    assert queue.is_absolute() and queue.is_dir(), "Missing durable outbox path"
    changed = False
    bridge_stopped = False
    backup = root / "backup"
    backup.mkdir(mode=0o700)
    upgrade_command = ["runuser", "-u", "odoo", "--", "/opt/odoo/venv/bin/python3", "/opt/odoo/odoo19/odoo-bin",
        "-c", "/opt/odoo/config/odoo.conf", "-d", "odoo-26-1-16", "--db-filter=^odoo-26-1-16$",
        "-u", "iot_control_center", "--stop-after-init", "--no-http", "--workers=0", "--max-cron-threads=0",
        "--logfile=/dev/null"]
    try:
        run(["systemctl", "stop", "odoo"], "stop-odoo")
        run(["pg_dump", *pgargs, "-Fc", "-f", str(backup / "production.dump"), "odoo-26-1-16"], "database-backup", env=pg)
        run(["pg_restore", "--file=/dev/null", str(backup / "production.dump")], "database-backup-verify")
        shutil.copytree(live, backup / "addon")
        shutil.copy2("/usr/local/bin/iot_bridge", backup / "iot_bridge")
        shutil.copy2("/etc/iot_bridge.env", backup / "iot_bridge.env")
        assert inventory(backup / "addon") == accepted["installed_inventory"]
        assert hashlib.sha256((backup / "iot_bridge").read_bytes()).hexdigest() == accepted["old_bridge_sha256"]
        assert (backup / "iot_bridge.env").read_bytes() == Path("/etc/iot_bridge.env").read_bytes()
        run(["cp", "-a", "--reflink=auto", "/opt/odoo/data/filestore/odoo-26-1-16", str(backup / "filestore")], "filestore-backup")
        assert inventory(backup / "filestore") == inventory(Path("/opt/odoo/data/filestore/odoo-26-1-16"))
        before = sql_fingerprint("odoo-26-1-16")
        run(["systemctl", "stop", "iot-bridge"], "stop-bridge")
        bridge_stopped = True
        run(["cp", "-a", "--reflink=auto", str(queue), str(backup / "outbox")], "bridge-outbox-backup")
        assert inventory(queue) == inventory(backup / "outbox")
        changed = True
        for name in metadata["files"]:
            destination = live / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate / name, destination)
            shutil.chown(destination, user="root", group="odoo")
            os.chmod(destination, 0o640)
        run(["install", "-m", "755", str(binary), "/usr/local/bin/iot_bridge"], "install-tested-bridge")
        run(upgrade_command, "upgrade-production")
        assert inventory(live) == accepted["candidate_inventory"]
        assert sql_fingerprint("odoo-26-1-16") == before
        run(["systemctl", "start", "odoo", "iot-bridge"], "start-tested-services")
        run(["curl", "--retry", "15", "--retry-delay", "2", "--retry-connrefused", "--max-time", "5", "-fsS", "-o", "/dev/null", "http://192.168.10.15:8069/web/login"], "production-health")
        for service in ("odoo", "iot-bridge", "mosquitto"):
            assert subprocess.check_output(["systemctl", "is-active", service], text=True).strip() == "active"
        receipt = {"status":"published", "version":metadata["version"], "backup":str(backup),
            "patch_sha256":metadata["patch_sha256"], "bridge_sha256":accepted["bridge_sha256"],
            "published_at":time.strftime("%Y-%m-%d %H:%M:%S UTC",time.gmtime())}
        (stage / "production-receipt.json").write_text(json.dumps(receipt))
        emit("RELAY_LATENCY_PUBLISHED",receipt)
    except Exception:
        if changed:
            for name in metadata["files"]:
                if (backup / "addon" / name).exists():
                    shutil.copy2(backup / "addon" / name, live / name)
                elif (live / name).exists():
                    (live / name).unlink()
            shutil.copy2(backup / "iot_bridge", "/usr/local/bin/iot_bridge")
            # Restore XML view classes as well if the new upgrade had committed.
            # Never overwrite live business data with a database restore here.
            with (root / "restore-prior-views.log").open("wb") as log:
                restored = subprocess.run(upgrade_command, stdout=log, stderr=log, timeout=1800)
            emit("RESTORE_PRIOR_VIEWS", {"success": restored.returncode == 0})
        subprocess.run(["systemctl", "start", "odoo"])
        if bridge_stopped: subprocess.run(["systemctl", "start", "iot-bridge"])
        raise
