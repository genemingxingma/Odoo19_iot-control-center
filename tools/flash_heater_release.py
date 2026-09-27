"""Flash a reviewed heater application in one session, preserving device data.

Device identities and approved hashes belong in an external manifest, not Git.
Heater load isolation must have been confirmed physically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FLASH_BYTES = 4 * 1024 * 1024
DATA_START = 0x100000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def external_path(value):
    path = Path(value).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Protected device metadata and backups must be outside the repository")
    return path


def validate_manifest(path):
    m = json.loads(external_path(path).read_text(encoding="utf-8"))
    for field in ("backup_sha256", "image_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", m[field]):
            raise ValueError("Invalid approved digest")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", m["expected_mac"]):
        raise ValueError("Invalid expected controller identity")
    if not re.fullmatch(r"[0-9A-F]{16}", m["sensor_rom"]):
        raise ValueError("Invalid expected probe identity")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?", m["firmware"]):
        raise ValueError("Invalid firmware version")
    if not isinstance(m["version_number"], int) or m["version_number"] < 1:
        raise ValueError("Invalid monotonic firmware number")
    for field in ("backup", "candidate", "receipt", "preflash_backup"):
        m[field] = external_path(m[field])
    if m.get("reuse_data_backup"):
        m["reuse_data_backup"] = external_path(m["reuse_data_backup"])
        if len(m["reuse_data_backup"].read_bytes()) != FLASH_BYTES or digest(m["reuse_data_backup"]) != m["reuse_data_backup_sha256"]:
            raise ValueError("Reusable protected backup verification failed")
    m["image"] = Path(m["image"]).resolve()
    if len(m["backup"].read_bytes()) != FLASH_BYTES or digest(m["backup"]) != m["backup_sha256"]:
        raise ValueError("Protected original backup verification failed")
    image = m["image"].read_bytes()
    marker = f'IMYTESTFW1:heater:heater-esp12s-ds18b20-v1:{m["version_number"]}:END'.encode()
    if digest(m["image"]) != m["image_sha256"] or not 0 < len(image) < DATA_START or image[0] != 0xE9 or marker not in image:
        raise ValueError("Reviewed application image verification failed")
    return m


def verify_runtime(m, samples, receipt):
    if receipt.get("candidate_sha256") != m["image_sha256"] or not receipt.get("data_region_unchanged"):
        raise ValueError("Runtime receipt does not match a verified application-only write")
    if receipt.get("phase") not in ("write_hash_verified_awaiting_runtime", "verified_running"):
        raise ValueError("Write did not complete successfully")
    if len(samples) < 3 or samples[-1].get("uptime_ms", 0) - samples[0].get("uptime_ms", 0) < 60000:
        raise ValueError("At least one minute of continuous runtime samples is required")
    expected_id = "HTR-" + m["expected_mac"].replace(":", "").upper()
    for s in samples:
        if s.get("firmware") != m["firmware"] or s.get("device_id") != expected_id:
            raise ValueError("Runtime controller or firmware mismatch")
        if s.get("enabled") is not False or s.get("output") is not False:
            raise ValueError("Heater did not remain off")
        if s.get("settings_ready") is not True or s.get("temperature_record_interval_s") != 3600:
            raise ValueError("Offline settings or hourly record policy is unavailable")
        if s.get("setpoint_source") not in ("default", "saved") or not 10 <= s.get("target", 0) <= 50:
            raise ValueError("Invalid runtime setpoint")
        if s.get("setpoint_source") == "default" and s.get("target") != 42:
            raise ValueError("Unexpected offline default setpoint")
        if s.get("detected_sensor_count") != 1 or s.get("detected_sensor_rom") != m["sensor_rom"]:
            raise ValueError("Probe inventory mismatch")
        if any(s.get(key) is not True for key in ("storage", "journal_healthy", "display_ready", "temperature_valid", "probe_matches_binding", "probe_external_power", "probe_scratchpad_valid")):
            raise ValueError("Probe, storage or display validation failed")
        if s.get("loop_fault_this_boot") is not False or s.get("loop_trip_gap_ms") != 0 or s.get("probe_crc_error") is not False:
            raise ValueError("New safety or CRC failure during observation")
        if s.get("fault") == "loop_stalled" and s.get("loop_fault_restored") is not True:
            raise ValueError("Unexplained loop fault")
        if s.get("fault") == "storage" and s.get("storage_fault_restored") is not True:
            raise ValueError("Unexplained storage fault")
    if samples[-1].get("probe_scan_count", 0) < 2:
        raise ValueError("Periodic probe rescan was not observed")


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def flash(m, args):
    sys.path.insert(0, str(args.esptool_dir))
    import esptool
    from esptool.cmds import DETECTED_FLASH_SIZES
    esp = esptool.get_default_connected_device([args.port], args.port,
        args.connect_attempts, args.connect_baud, chip="esp8266", before="no_reset")
    receipt = {"phase": "identity_verified", "candidate_sha256": m["image_sha256"],
        "original_backup_sha256": m["backup_sha256"], "candidate_bytes": m["candidate"].stat().st_size,
        "application_offset": "0x000000", "heater_load_off": True,
        "data_region_unchanged": False, "write_started": False}
    try:
        mac = ":".join(f"{byte:02x}" for byte in esp.read_mac())
        if mac != m["expected_mac"]:
            raise ValueError("Connected controller does not match the protected backup")
        esp = esp.run_stub()
        if DETECTED_FLASH_SIZES.get((esp.flash_id() >> 16) & 0xFF) != "4MB":
            raise ValueError("Unexpected flash capacity")
        esp.change_baud(args.baud)
        print("HEATER_IDENTITY_VERIFIED_BACKING_UP", flush=True)
        last_percent = -10
        def progress(done, total):
            nonlocal last_percent
            percent = done * 100 // total
            if percent >= last_percent + 10:
                print(f"HEATER_PREFLASH_BACKUP {percent}%", flush=True); last_percent = percent
        reusable = m.get("reuse_data_backup")
        prior = reusable.read_bytes() if reusable else b""
        if prior and esp.flash_md5sum(DATA_START, FLASH_BYTES - DATA_START).lower() == hashlib.md5(prior[DATA_START:]).hexdigest():
            print("HEATER_PROTECTED_DATA_REVALIDATED_READING_CURRENT_APPLICATION", flush=True)
            before = esp.read_flash(0, DATA_START, progress) + prior[DATA_START:]
        else:
            before = esp.read_flash(0, FLASH_BYTES, progress)
        if len(before) != FLASH_BYTES:
            raise ValueError("Incomplete preflash backup; no write performed")
        if esp.flash_md5sum(0, FLASH_BYTES).lower() != hashlib.md5(before).hexdigest():
            raise ValueError("Fresh full backup does not match the controller; no write performed")
        m["preflash_backup"].write_bytes(before)
        receipt["preflash_backup_sha256"] = hashlib.sha256(before).hexdigest()
        receipt["phase"] = "backed_up"; save(m["receipt"], receipt)
        # Keep one serial session across identity, backup, write and hash checks.
        esp.sync()
        if not esp.sync_stub_detected:
            raise ValueError("Flasher stub identity was lost; refusing a write")
        receipt["write_started"] = True; receipt["phase"] = "writing"; save(m["receipt"], receipt)
        esptool.main(["--chip", "esp8266", "--baud", str(args.baud), "--before", "no_reset_no_sync",
            "--after", "no_reset_stub", "write_flash", "--flash_mode", "keep",
            "--flash_freq", "keep", "--flash_size", "keep", "0", str(m["candidate"])], esp=esp)
        retained_md5 = hashlib.md5(before[DATA_START:]).hexdigest()
        if esp.flash_md5sum(DATA_START, FLASH_BYTES - DATA_START).lower() != retained_md5:
            raise ValueError("Non-application flash changed; keep heater load disconnected")
        receipt["data_region_unchanged"] = True
        receipt["phase"] = "write_hash_verified_awaiting_runtime"
        receipt["esptool_write_hash_verified"] = True
        save(m["receipt"], receipt)
        esp.soft_reset(False)
        print("HEATER_RELEASE_WRITE_HASH_VERIFIED_AWAITING_RUNTIME", flush=True)
    except Exception as exc:
        receipt["failed_stage"] = receipt["phase"]
        receipt["phase"] = "failed"; receipt["error_type"] = type(exc).__name__
        save(m["receipt"], receipt)
        raise
    finally:
        esp._port.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--port")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm-heater-load-off", action="store_true")
    p.add_argument("--runtime-status", type=Path)
    p.add_argument("--connect-attempts", type=int, default=120)
    p.add_argument("--connect-baud", type=int, choices=(115200, 230400, 460800), default=115200)
    p.add_argument("--baud", type=int, choices=(115200, 230400, 460800), default=115200)
    p.add_argument("--esptool-dir", type=Path, default=Path.home() / ".platformio/packages/tool-esptoolpy")
    args = p.parse_args(); m = validate_manifest(args.manifest)
    if args.runtime_status:
        receipt = json.loads(m["receipt"].read_text(encoding="utf-8"))
        samples = json.loads(args.runtime_status.read_text(encoding="utf-8"))
        verify_runtime(m, samples, receipt)
        receipt.update(phase="verified_running", runtime_samples=len(samples), runtime_firmware=m["firmware"], runtime_output_off=True)
        save(m["receipt"], receipt); print("HEATER_RELEASE_RUNTIME_VERIFIED")
        return
    if not args.execute:
        print("HEATER_RELEASE_MANIFEST_VALIDATED"); return
    if not args.port or not args.confirm_heater_load_off or not 1 <= args.connect_attempts <= 120:
        raise ValueError("Bounded handshake, port and physical heater isolation are required")
    if m["receipt"].exists() or m["preflash_backup"].exists():
        raise ValueError("Existing release evidence; refusing a repeated write")
    if not m["candidate"].exists(): shutil.copy2(m["image"], m["candidate"])
    if digest(m["candidate"]) != m["image_sha256"]:
        raise ValueError("Protected candidate image mismatch")
    flash(m, args)


if __name__ == "__main__":
    main()
