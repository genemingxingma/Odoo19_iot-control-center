"""Release the exact rehearsed instrument candidate to imytestth production."""
import argparse
import shlex
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rehearsal",
        required=True,
        help="Verified /opt/odoo/module_backups/iot_instruments_test_* directory",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise RuntimeError("Production release requires --execute")
    if not args.rehearsal.startswith("/opt/odoo/module_backups/iot_instruments_test_"):
        raise RuntimeError("Refusing an unverified rehearsal path")
    config = read_config()
    client = connect("192.168.10.15", config)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    release = "/opt/odoo/module_backups/iot_instruments_production_" + stamp
    try:
        _, out, _ = client.exec_command("hostname")
        if out.read().decode().strip() != "imytestth":
            raise RuntimeError("Refusing a non-production host")
        with client.open_sftp() as sftp:
            sftp.put(
                str(ROOT / "tools" / "instrument_release_production.sh"),
                "/tmp/instrument_release_production.sh",
            )
        command = "bash /tmp/instrument_release_production.sh %s %s" % (
            shlex.quote(args.rehearsal),
            shlex.quote(release),
        )
        rc, output = execute_sudo(client, command, config["REMOTE_PASSWORD"], 2400)
        print(output)
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
