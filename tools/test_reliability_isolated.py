"""Test synthetic data in an isolated imytestth DB without touching production."""
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
    stage = "/tmp/iot_reliability_" + stamp
    database = "iot_reliability_" + stamp
    try:
        _, out, _ = client.exec_command("hostname")
        assert out.read().decode().strip() == "imytestth"
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
            sftp.put(str(ROOT / "tools/test_reliability_isolated.sh"), stage + ".sh")
        rc, output = execute_sudo(client, "bash " + shlex.quote(stage + ".sh") + " " + shlex.quote(stage) + " " + database,
                                  config["REMOTE_PASSWORD"], 1200)
        print(output)
        print("TEST_ARTIFACTS", stage, "DATABASE", database, flush=True)
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
