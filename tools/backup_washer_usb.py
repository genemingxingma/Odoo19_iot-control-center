"""Read and verify a complete washer flash image without writing the device."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone


BACKUP_ROOT = Path("D:/Codex/device_backups").resolve()
FLASH_BYTES = 0x400000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--expected-mac", required=True)
    parser.add_argument("--esptool-dir", type=Path,
                        default=Path.home() / ".platformio/packages/tool-esptoolpy")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-actuator-power-off", action="store_true")
    args = parser.parse_args()

    output = args.output_dir.resolve()
    if not output.is_relative_to(BACKUP_ROOT):
        raise RuntimeError("A protected device-backup directory is required")
    if not args.execute:
        print(json.dumps({"dry_run": True, "bytes": FLASH_BYTES,
                          "output_dir": str(output), "serial_opened": False}))
        return
    if not args.confirm_actuator_power_off:
        parser.error("Execution requires confirmed actuator power isolation")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("Backup directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(args.esptool_dir))
    from esptool.reset import ClassicReset
    from esptool.targets.esp32 import ESP32ROM

    chip = ESP32ROM(args.port, 115200)
    try:
        # Keep reset, synchronization, reading and verification in one serial
        # session. This avoids CH340 control-line changes when a port is reopened.
        ClassicReset(chip._port, reset_delay=0.2)()
        chip.connect(mode="no_reset", attempts=2)
        if not chip.get_chip_description().startswith("ESP32-D0WD-V3"):
            raise RuntimeError("Unexpected controller model")
        mac = bytes(chip.read_mac()).hex()
        if mac != args.expected_mac.replace(":", "").lower():
            raise RuntimeError("Unexpected controller identity")
        chip = chip.run_stub()
        chip.change_baud(460800)

        def progress(done, total):
            if done % 0x40000 == 0 or done == total:
                print(f"BACKUP_READ_BYTES {done}/{total}", flush=True)

        raw = chip.read_flash(0, FLASH_BYTES, progress)
        if len(raw) != FLASH_BYTES:
            raise RuntimeError("Incomplete flash read")
        device_md5 = chip.flash_md5sum(0, FLASH_BYTES).lower()
        local_md5 = hashlib.md5(raw).hexdigest()
        if device_md5 != local_md5:
            raise RuntimeError("Device and backup MD5 values differ")
    finally:
        chip._port.close()

    backup = output / "original-flash-4mb.bin"
    backup.write_bytes(raw)
    receipt = {
        "backup_file": str(backup),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "md5": local_md5,
        "device_md5": device_md5,
        "verify_flash_passed": True,
        "size": len(raw),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "port": args.port,
        "chip": "ESP32-D0WD-V3",
        "mac": mac,
        "actuator_power_confirmed_off": True,
        "flash_written": False,
        "flash_erased": False,
    }
    (output / "backup-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print("BACKUP_VERIFIED " + json.dumps(receipt))


if __name__ == "__main__":
    main()
