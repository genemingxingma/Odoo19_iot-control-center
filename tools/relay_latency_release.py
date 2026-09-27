"""Transport only the reviewed relay-latency patch to the verified host."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILES = ("__manifest__.py", "controllers/internal_ingest.py", "models/iot_mqtt_message.py",
         "models/iot_device.py", "views/iot_device_views.xml", "static/src/js/relay_live_refresh.js",
         "tests/test_internal_ingest_http.py", "tests/test_relay_views.py")
sys.path.insert(0, "D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("test", "publish"))
    p.add_argument("--stage")
    args = p.parse_args()
    if args.mode == "publish" and not args.stage:
        p.error("Publish only the already tested stage")
    stage = args.stage or "/home/mamingxing/iot-relay-latency-" + uuid.uuid4().hex[:12]
    if not stage.startswith("/home/mamingxing/iot-relay-latency-") or len(stage.rsplit("-", 1)[-1]) != 12:
        raise ValueError("Invalid stage")
    cfg = read_config()
    client = connect("192.168.10.15", cfg)
    try:
        _, out, _ = client.exec_command("hostname")
        assert out.read().decode().strip() == "imytestth"
        if args.mode == "test":
            files, baseline = {}, {}
            patch = io.BytesIO()
            with tarfile.open(fileobj=patch, mode="w:gz") as archive:
                for name in FILES:
                    raw = (ROOT / name).read_bytes()
                    files[name] = hashlib.sha256(raw).hexdigest()
                    archive.add(ROOT / name, arcname=name)
                    old = subprocess.run(["git", "show", "HEAD:" + name], cwd=ROOT, capture_output=True)
                    baseline[name] = hashlib.sha256(old.stdout.replace(b"\r\n", b"\n")).hexdigest() if old.returncode == 0 else None
            bridge = io.BytesIO()
            with tarfile.open(fileobj=bridge, mode="w:gz") as archive:
                for name in ("Cargo.toml", "Cargo.lock", "src/main.rs", "src/outbox.rs"):
                    archive.add(ROOT / "middleware/iot_bridge" / name, arcname=name)
            metadata = {"schema": 1, "version": "19.0.2.6.1", "files": files, "baseline": baseline,
                "patch_sha256": hashlib.sha256(patch.getvalue()).hexdigest(),
                "bridge_source_sha256": hashlib.sha256(bridge.getvalue()).hexdigest()}
            with client.open_sftp() as sftp:
                sftp.mkdir(stage, mode=0o700)
                for name, content in (("patch.tgz", patch.getvalue()), ("bridge.tgz", bridge.getvalue()),
                                      ("package.json", json.dumps(metadata).encode())):
                    with sftp.open(stage + "/" + name, "wb") as handle:
                        handle.write(content)
                    sftp.chmod(stage + "/" + name, 0o600)
                sftp.put(str(ROOT / "tools/relay_latency_server.py"), stage + "/server.py")
        rc, output = execute_sudo(client, shlex.join([
            "/usr/bin/python3", stage + "/server.py", args.mode, stage,
        ]), cfg["REMOTE_PASSWORD"], 2400)
        print(output)
        print("RELAY_LATENCY_STAGE", stage)
        raise SystemExit(rc)
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
