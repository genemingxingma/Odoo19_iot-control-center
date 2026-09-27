"""Run the guarded washer-program publication through the approved SSH helper."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import sys


sys.path.insert(0, r"D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config  # noqa: E402


HOST = "192.168.10.15"
DATABASE = "odoo-26-1-16"
REMOTE_STAGE = "/opt/odoo/module_backups/washer_test_programs_20260922"
REMOTE_UPLOAD = "/home/mamingxing/.washer-test-programs.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "apply", "verify"))
    args = parser.parse_args()
    config = read_config()
    client = connect(HOST, config)
    try:
        with client.open_sftp() as sftp:
            sftp.put("tools/push_washer_test_programs_orm.py", REMOTE_UPLOAD)
            sftp.chmod(REMOTE_UPLOAD, 0o600)
        rc, _ = execute_sudo(
            client,
            shlex.join(["install", "-d", "-o", "odoo", "-g", "odoo", "-m", "700", REMOTE_STAGE]),
            config["REMOTE_PASSWORD"],
            30,
        )
        assert rc == 0
        remote_script = REMOTE_STAGE + "/programs.py"
        rc, _ = execute_sudo(
            client,
            shlex.join(["install", "-o", "odoo", "-g", "odoo", "-m", "600", REMOTE_UPLOAD, remote_script]),
            config["REMOTE_PASSWORD"],
            30,
        )
        assert rc == 0
        shell = shlex.join([
            "/opt/odoo/venv/bin/python3",
            "/opt/odoo/odoo19/odoo-bin",
            "shell",
            "-c",
            "/opt/odoo/config/odoo.conf",
            "-d",
            DATABASE,
            "--no-http",
            "--max-cron-threads=0",
            "--logfile=" + REMOTE_STAGE + "/" + args.mode + ".log",
        ]) + " < " + remote_script
        command = [
            "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            "-p", "User=odoo",
            "-p", "IPAddressDeny=any",
            "-p", "IPAddressAllow=192.168.10.20",
            "-p", "MemoryMax=1G",
            "-p", "NoNewPrivileges=yes",
            "/usr/bin/env", "WASHER_PROGRAM_MODE=" + args.mode,
            "bash", "-c", shell,
        ]
        rc, output = execute_sudo(client, shlex.join(command), config["REMOTE_PASSWORD"], 180)
        if rc != 0:
            raise RuntimeError("Remote Odoo operation failed; inspect the protected server log")
        line = next(
            value for value in output.splitlines()
            if value.startswith("WASHER_TEST_PROGRAM_RESULT ")
        )
        result = json.loads(line.split(" ", 1)[1])
        receipt = Path("deploy/artifacts") / (
            "washer-test-programs-" + args.mode + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
        )
        receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({
            "mode": result["mode"],
            "catalog_count": result["catalog_count"],
            "catalog_labels": result["catalog_labels"],
            "sync_matches": result["sync_matches"],
            "online": result["online"],
            "status_fresh": result["status_fresh"],
            "receipt": str(receipt),
        }, ensure_ascii=False))
    finally:
        client.close()


if __name__ == "__main__":
    main()
