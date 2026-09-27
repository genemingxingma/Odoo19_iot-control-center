"""Flash and verify the reviewed heater application without touching LittleFS."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SAFE_ROOT = Path(r"D:\Codex\device_backups\heater\2026-09-27")
BACKUP = SAFE_ROOT / "heater-esp8266-original-c82b962d09d7-4mb.bin"
BUILD = ROOT / "firmware/instruments/.pio/build/heater/firmware.bin"
CANDIDATE = SAFE_ROOT / "heater-3.2.0-rc6-32005.bin"
RECEIPT = SAFE_ROOT / "heater-3.2.0-rc6-flash-receipt.json"
BACKUP_SHA256 = "dccc5a4b249391051e2e402fd5f85e090b933f3676d90031a2fab4a501648e84"
CANDIDATE_SHA256 = "fd1b9259bf2fdedf42f0690e80988846fcf757da571674a92966f65670c49411"
EXPECTED_MAC = "c8:2b:96:2d:09:d7"
MARKER = b"IMYTESTFW1:heater:heater-esp12s-ds18b20-v1:32005:END"
PYTHON = ROOT / "deploy/artifacts/instrument-venv/Scripts/python.exe"
ESPTOOL = Path.home() / ".platformio/packages/tool-esptoolpy/esptool.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, capture=False):
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def save(value):
    RECEIPT.write_text(json.dumps(value, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-heater-load-off", action="store_true")
    parser.add_argument("--runtime-status", type=Path)
    args = parser.parse_args()

    backup = BACKUP.read_bytes()
    build = BUILD.read_bytes()
    assert len(backup) == 4 * 1024 * 1024 and digest(BACKUP) == BACKUP_SHA256
    assert hashlib.sha256(build).hexdigest() == CANDIDATE_SHA256
    assert build[:1] == b"\xe9" and len(build) < 0x100000 and MARKER in build
    if not CANDIDATE.exists():
        shutil.copy2(BUILD, CANDIDATE)
    assert digest(CANDIDATE) == CANDIDATE_SHA256

    if args.runtime_status:
        if not RECEIPT.exists():
            raise RuntimeError("No write receipt is available for runtime verification")
        statuses = json.loads(args.runtime_status.read_text(encoding="utf-8"))
        if len(statuses) < 3:
            raise RuntimeError("At least three runtime samples are required")
        for status in statuses:
            if status.get("firmware") != "3.2.0-rc6":
                raise RuntimeError("Unexpected runtime firmware")
            if status.get("device_id") != "HTR-C82B962D09D7":
                raise RuntimeError("Unexpected runtime device ID")
            if status.get("output") or status.get("enabled"):
                raise RuntimeError("Heater output is not safely off")
            if status.get("detected_sensor_rom") != "28A061BB0E00006F":
                raise RuntimeError("Unexpected temperature probe")
            if not status.get("storage") or not status.get("display_ready"):
                raise RuntimeError("Storage or display did not initialize")
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if receipt.get("candidate_sha256") != CANDIDATE_SHA256:
            raise RuntimeError("Runtime receipt does not match the written image")
        receipt["phase"] = "verified_running"
        receipt["runtime_samples"] = len(statuses)
        receipt["runtime_firmware"] = "3.2.0-rc6"
        receipt["runtime_device_id"] = "HTR-C82B962D09D7"
        receipt["runtime_output_off"] = True
        save(receipt)
        print("HEATER_RELEASE_RUNTIME_VERIFIED")
        return

    if not args.port:
        raise RuntimeError("--port is required for validation or flashing")

    receipt = {
        "phase": "validated",
        "device_mac": EXPECTED_MAC,
        "original_backup_sha256": BACKUP_SHA256,
        "candidate_sha256": CANDIDATE_SHA256,
        "candidate_bytes": len(build),
        "application_offset": "0x000000",
        "filesystem_unchanged": True,
        "heater_load_off": bool(args.confirm_heater_load_off),
    }
    if not args.execute:
        print(json.dumps(receipt))
        return
    if not args.confirm_heater_load_off:
        raise RuntimeError("Heater load isolation was not confirmed")
    if RECEIPT.exists():
        raise RuntimeError("Release receipt already exists; refusing a repeated write")

    base = [
        str(PYTHON), str(ESPTOOL), "--chip", "esp8266", "--port", args.port,
        "--baud", "115200", "--before", "no_reset", "--after", "no_reset",
    ]
    identity = run(base + ["--no-stub", "flash_id"], capture=True)
    output = identity.stdout + identity.stderr
    if f"MAC: {EXPECTED_MAC}" not in output or "Detected flash size: 4MB" not in output:
        raise RuntimeError("Connected controller does not match the protected backup")

    receipt["phase"] = "writing"
    save(receipt)
    write = [
        str(PYTHON), str(ESPTOOL), "--chip", "esp8266", "--port", args.port,
        "--baud", "460800", "--before", "no_reset", "--after", "soft_reset",
    ]
    try:
        run(write + [
            "write_flash", "--flash_mode", "keep", "--flash_freq", "keep",
            "--flash_size", "keep", "0x000000", str(CANDIDATE),
        ])
        receipt["phase"] = "write_hash_verified_awaiting_runtime"
        receipt["esptool_write_hash_verified"] = True
        save(receipt)
    except Exception as exc:
        receipt["phase"] = "failed"
        receipt["error_type"] = type(exc).__name__
        raise
    finally:
        save(receipt)
    print("HEATER_RELEASE_WRITE_HASH_VERIFIED_AWAITING_RUNTIME")


if __name__ == "__main__":
    main()
