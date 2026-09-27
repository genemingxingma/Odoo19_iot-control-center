"""Rehearse the candidate against a protected copy of imytestth production."""
import io
import shlex
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config


def main():
    config = read_config()
    client = connect("192.168.10.15", config)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stage = "/opt/odoo/module_backups/iot_instruments_test_" + stamp
    database = "iot_instruments_upgrade_" + stamp
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for folder in ("controllers", "core", "data", "deploy", "i18n", "migrations", "models", "security", "services", "static", "tests", "views", "wizard"):
            for path in (ROOT / folder).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    tar.add(path, arcname="iot_control_center/" + path.relative_to(ROOT).as_posix())
        for name in ("__init__.py", "__manifest__.py", "hooks.py"):
            tar.add(ROOT / name, arcname="iot_control_center/" + name)
    archive.seek(0)
    try:
        _, out, _ = client.exec_command("hostname")
        if out.read().decode().strip() != "imytestth":
            raise RuntimeError("Refusing a non-production-test host")
        with client.open_sftp() as sftp:
            sftp.putfo(archive, "/tmp/iot-instrument-upgrade-candidate.tgz")
            sftp.put(str(ROOT / "tools" / "instrument_upgrade_isolated.sh"), "/tmp/instrument_upgrade_isolated.sh")
        command = "bash /tmp/instrument_upgrade_isolated.sh %s %s" % (shlex.quote(stage), shlex.quote(database))
        rc, output = execute_sudo(client, command, config["REMOTE_PASSWORD"], 2400)
        print(output)
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
