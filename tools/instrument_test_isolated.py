"""Run instrument tests in a new, synthetic database on imytestth.

Reuses the approved credential helper; never touches the running Odoo service,
its addon directory or its database. Artifacts remain for diagnosis.
"""
import io
import shlex
import sys
import tarfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config


def main():
    config = read_config()
    client = connect("192.168.10.15", config)
    stamp = uuid.uuid4().hex[:12]
    stage = "/tmp/iot_instruments_" + stamp
    database = "iot_instruments_" + stamp
    try:
        _, out, _ = client.exec_command("hostname")
        if out.read().decode().strip() != "imytestth":
            raise RuntimeError("Refusing a non-test host")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for folder in ("controllers", "core", "data", "i18n", "migrations", "models", "security", "services", "static", "tests", "views", "wizard"):
                for path in (ROOT / folder).rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                        tar.add(path, arcname="iot_control_center/" + path.relative_to(ROOT).as_posix())
            for name in ("__init__.py", "__manifest__.py", "hooks.py"):
                tar.add(ROOT / name, arcname="iot_control_center/" + name)
        archive.seek(0)
        with client.open_sftp() as sftp:
            sftp.putfo(archive, stage + ".tgz")
            sftp.put(str(ROOT / "tools" / "instrument_test_isolated.sh"), stage + ".sh")
            sftp.put(str(ROOT / "tools" / "instrument_export_i18n.py"), stage + "_i18n.py")
        command = "bash " + shlex.quote(stage + ".sh") + " " + shlex.quote(stage) + " " + database
        rc, output = execute_sudo(client, command, config["REMOTE_PASSWORD"], 1200)
        print(output)
        if rc == 0:
            destination = ROOT / "deploy/artifacts/instrument-native.pot"
            with client.open_sftp() as sftp:
                sftp.get(stage + "/addons/iot_control_center/i18n/iot_control_center.pot", str(destination))
        print("TEST_ARTIFACTS", stage, "DATABASE", database)
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
