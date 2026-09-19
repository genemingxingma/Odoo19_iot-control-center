"""Upload a verified TJC TFT through the RAM-only ESP32 USB bridge.

Dry-run is the default and does not open a serial port. A matching ESP32 image
must be installed and held in ROM before --execute. Never boot the legacy app
with the V3 screen. Protocol: TJC HMI download protocol, whmi-wri/4096-byte ACK.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

from probe_washer_usb_screen import bridge_artifacts, read_until, READY, END, ROOT

MODEL = "TJC8048X550_011C"
BAUD = 115200
BLOCK = 4096


def verified_tft(path, expected_sha256):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        raise ValueError("A full approved SHA-256 is required")
    raw = path.read_bytes()
    if not 4096 <= len(raw) <= 32 * 1024 * 1024:
        raise ValueError("TFT file size is outside this tool's bounds")
    if hashlib.sha256(raw).hexdigest() != expected_sha256.lower():
        raise ValueError("TFT file does not match the approved artifact")
    return raw


def write_all(port, data):
    position = 0
    while position < len(data):
        written = port.write(data[position:])
        if not written or written > len(data) - position:
            raise IOError("Serial write made no progress or returned an invalid size")
        position += written
    port.flush()


def wait_ack(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        byte = port.read(1)
        if byte == b"\x05":
            return
        if byte:
            raise RuntimeError(f"Unexpected TFT response 0x{byte[0]:02x}; no automatic retry")
    raise TimeoutError("TFT ACK timeout; transfer stopped without resending a block")


def transfer(port, raw, progress):
    # Do not silently retry: a lost acknowledgement leaves the offset ambiguous.
    write_all(port, f"whmi-wri {len(raw)},{BAUD},0".encode("ascii") + END)
    wait_ack(port, 5)
    progress(0)
    for offset in range(0, len(raw), BLOCK):
        chunk = raw[offset:offset + BLOCK]
        write_all(port, chunk)
        wait_ack(port, 60 if offset + len(chunk) == len(raw) else 15)
        progress(offset + len(chunk))


def screen_identity(reply):
    found = re.search(rb"comok [^\r\n\xff]+", reply)
    if not found:
        raise ValueError("Missing complete screen connect reply")
    parts = found.group().split(b",")
    if len(parts) != 7 or parts[2].decode("ascii") != MODEL:
        raise ValueError("Screen identity does not match the approved model")
    capacity_field = parts[-1]
    # Exact extended response observed on this verified X5 model. Do not silently
    # discard arbitrary suffixes or accept a different addressed-screen variant.
    if capacity_field == b"128974848-0":
        capacity_field = b"128974848"
    if not re.fullmatch(rb"[0-9]{4,9}", capacity_field):
        raise ValueError("Unsupported screen capacity/address response")
    capacity = int(capacity_field)
    if not 4096 <= capacity <= 128 * 1024 * 1024:
        raise ValueError("Invalid screen flash capacity")
    return capacity


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("tft", type=Path)
    p.add_argument("--sha256", required=True)
    p.add_argument("--port", required=True)
    p.add_argument("--expected-mac", required=True)
    p.add_argument("--artifacts", type=Path, default=ROOT / "firmware/instruments/out/maintenance")
    p.add_argument("--esptool-dir", type=Path, default=Path.home() / ".platformio/packages/tool-esptoolpy")
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm-actuator-power-off", action="store_true")
    p.add_argument("--confirm-paired-controller-installed", action="store_true")
    a = p.parse_args()
    raw = verified_tft(a.tft, a.sha256)
    entry, segments = bridge_artifacts(a.artifacts)
    if not a.execute:
        print(json.dumps({"dry_run": True, "bytes": len(raw), "sha256": a.sha256.lower(),
                          "model": MODEL, "serial_opened": False}))
        return
    if not a.confirm_actuator_power_off or not a.confirm_paired_controller_installed:
        p.error("Execution requires actuator isolation and matching controller installation")
    if a.receipt.exists():
        p.error("Use a new receipt path; previous transfer evidence will not be overwritten")
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    result = {"model": MODEL, "sha256": a.sha256.lower(), "bytes": len(raw),
              "transfer_attempted": False, "acknowledged_bytes": 0,
              "v3_heartbeat_verified": False, "returned_to_rom": False,
              "esp32_flash_written": False}

    def save():
        a.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    save()
    sys.path.insert(0, str(a.esptool_dir))
    from esptool.targets.esp32 import ESP32ROM
    esp = ESP32ROM(a.port, BAUD)
    launched = False
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            esp.connect(mode="default_reset", attempts=2)
            if not esp.get_chip_description().startswith("ESP32-D0WD-V3"):
                raise RuntimeError("Unexpected ESP32 model")
            if bytes(esp.read_mac()).hex() != a.expected_mac.replace(":", "").lower():
                raise RuntimeError("Unexpected ESP32 identity")
            for address, data in segments:
                esp.mem_begin(len(data), 1, len(data), address)
                esp.mem_block(data, 0)
            launched = True
            esp.mem_finish(entry)
        port = esp._port
        port.timeout = 0.05
        port.write_timeout = 3
        read_until(port, READY)
        time.sleep(0.1)
        port.reset_input_buffer()
        write_all(port, b"\x00" + END)
        time.sleep(0.15)
        port.reset_input_buffer()
        write_all(port, b"connect" + END)
        capacity = screen_identity(read_until(port, END))
        time.sleep(0.1)
        port.reset_input_buffer()
        write_all(port, b"connect" + END)
        if screen_identity(read_until(port, END)) != capacity:
            raise ValueError("Screen identity/capacity changed between probes")
        if len(raw) > capacity:
            raise ValueError("TFT is larger than the connected screen's flash")
        time.sleep(0.1)
        port.reset_input_buffer()
        result["transfer_attempted"] = True
        save()

        def progress(count):
            result["acknowledged_bytes"] = count
            save()
            if count % (16 * BLOCK) == 0 or count == len(raw):
                print(f"SCREEN_ACK_BYTES {count}/{len(raw)}", flush=True)

        transfer(port, raw, progress)
        # Final block acknowledgement is not proof that the project booted.
        read_until(port, b"UI|HELLO|3\n", timeout=90)
        read_until(port, b"UI|HELLO|3\n", timeout=5)
        result["v3_heartbeat_verified"] = True
        save()
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        raise
    finally:
        try:
            if launched:
                with contextlib.redirect_stdout(io.StringIO()):
                    esp = ESP32ROM(esp._port, BAUD)
                    esp.connect(mode="default_reset", attempts=2)
                    result["returned_to_rom"] = esp.get_chip_description().startswith("ESP32-D0WD-V3")
        finally:
            esp._port.close()
            save()
            print(json.dumps(result))


if __name__ == "__main__":
    main()
