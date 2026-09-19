"""RAM-only USB/UART2 probe; never writes either device's firmware.

Requires a classic ESP32 washer with powered screen and isolated motor/pump
supplies. Firmware upgrading is intentionally NOT exposed by this diagnostic.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
READY = b"IMYTEST_RAM_BRIDGE_V1_READY"
ERROR = b"IMYTEST_RAM_BRIDGE_ERROR"
END = b"\xff\xff\xff"


def read_until(port, marker, timeout=3, limit=32768):
    deadline = time.monotonic() + timeout
    received = bytearray()
    while time.monotonic() < deadline and len(received) < limit:
        received.extend(port.read(min(max(port.in_waiting, 1), limit - len(received))))
        if ERROR in received:
            raise RuntimeError("RAM bridge detected a UART error and halted")
        if marker in received:
            return bytes(received)
    raise TimeoutError("Expected screen/bridge reply not received")


def bridge_artifacts(directory):
    elf = (directory / "bridge.elf").read_bytes()
    if len(elf) < 52 or elf[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", elf, 18)[0] != 94:
        raise ValueError("Not an ELF32 Xtensa image")
    entry = struct.unpack_from("<I", elf, 24)[0]
    segments = [(0x400BE000, (directory / "bridge-text.bin").read_bytes()),
                (0x3FFB0000, (directory / "bridge-data.bin").read_bytes())]
    if not (0 < len(segments[0][1]) <= 0x2000 and 0 < len(segments[1][1]) <= 0x8000):
        raise ValueError("Bridge segments exceed reserved RAM")
    if not 0x400BE000 <= entry < 0x400BE000 + len(segments[0][1]):
        raise ValueError("Bridge entry point outside IRAM")
    # Verify exported blobs against ELF load segments, not independent files.
    phoff = struct.unpack_from("<I", elf, 28)[0]
    phsize, phnum = struct.unpack_from("<HH", elf, 42)
    if phsize != 32 or not 1 <= phnum <= 16 or phoff < 52 or phoff + phsize * phnum > len(elf):
        raise ValueError("Invalid ELF program header table")
    for address, data in segments:
        matches = False
        for i in range(phnum):
            kind, offset, vaddr, _, size, _, _, _ = struct.unpack_from("<8I", elf, phoff + i * phsize)
            if kind == 1 and vaddr == address and elf[offset:offset + size] == data:
                matches = True
        if not matches:
            raise ValueError("Exported bridge blob does not match ELF")
    return entry, segments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--expected-mac", required=True)
    parser.add_argument("--confirm-actuator-power-off", action="store_true", required=True)
    parser.add_argument("--esptool-dir", type=Path,
                        default=Path.home() / ".platformio/packages/tool-esptoolpy")
    parser.add_argument("--artifacts", type=Path,
                        default=ROOT / "firmware/instruments/out/maintenance")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    entry, segments = bridge_artifacts(args.artifacts)
    sys.path.insert(0, str(args.esptool_dir))
    from esptool.targets.esp32 import ESP32ROM

    result = {"flash_written": False, "screen_firmware_written": False,
              "old_application_started": False, "ram_bridge_tested": False,
              "returned_to_rom": False, "screen_model": None,
              "bridge_sha256": [hashlib.sha256(data).hexdigest() for _, data in segments]}
    esp = ESP32ROM(args.port, 115200)
    launched = False
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            esp.connect(mode="default_reset", attempts=2)
            if not esp.get_chip_description().startswith("ESP32-D0WD-V3"):
                raise RuntimeError("This bridge is only validated for ESP32-D0WD-V3")
            if bytes(esp.read_mac()).hex() != args.expected_mac.replace(":", "").lower():
                raise RuntimeError("Device identity mismatch")
            for address, data in segments:
                esp.mem_begin(len(data), 1, len(data), address)
                esp.mem_block(data, 0)
            launched = True
            esp.mem_finish(entry)
        port = esp._port
        port.timeout = 0.05
        port.write_timeout = 2
        read_until(port, READY)
        time.sleep(0.1)
        port.reset_input_buffer()
        port.write(b"\x00" + END)
        port.flush()
        time.sleep(0.15)
        port.reset_input_buffer()
        port.write(b"connect" + END)
        port.flush()
        reply = read_until(port, END)
        model = re.search(rb"TJC[0-9A-Z_]{8,40}", reply)
        if b"comok" not in reply or not model:
            raise RuntimeError("Incomplete screen identity reply")
        result["screen_model"] = model.group().decode("ascii")
        if result["screen_model"] != "TJC8048X550_011C":
            raise RuntimeError("Screen model mismatch")
        # A long literal echo tests both UART directions without altering the UI.
        for i in range(16):
            token = (f"IOT_BRIDGE_{i:02d}_" + "0123456789ABCDEF" * 15).encode("ascii")
            time.sleep(0.1)
            port.reset_input_buffer()
            port.write(b'prints "' + token + b'",0' + END)
            port.flush()
            echoed = read_until(port, token, timeout=3)
            if token not in echoed:
                raise RuntimeError("Echo mismatch")
        result["echo_round_trips"] = 16
        result["echo_bytes_verified"] = 16 * len(token)
        # One near-4KiB burst exercises continuous forwarding and buffered replies.
        tokens = [(f"IOT_BURST_{i:02d}_" + "0123456789ABCDEF" * 15).encode("ascii")
                  for i in range(15)]
        burst = b"".join(b'prints "' + token + b'",0' + END for token in tokens)
        time.sleep(0.1)
        port.reset_input_buffer()
        port.write(burst)
        port.flush()
        echoed = read_until(port, tokens[-1], timeout=5)
        if b"".join(tokens) not in echoed:
            raise RuntimeError("Burst echo was truncated, duplicated or out of order")
        result["burst_transmitted_bytes"] = len(burst)
        result["burst_echo_bytes_verified"] = sum(map(len, tokens))
        result["ram_bridge_tested"] = True
    finally:
        try:
            if launched:
                with contextlib.redirect_stdout(io.StringIO()):
                    # Reset into ROM download mode, NEVER into the washer app.
                    esp = ESP32ROM(esp._port, 115200)
                    esp.connect(mode="default_reset", attempts=2)
                    result["returned_to_rom"] = esp.get_chip_description().startswith("ESP32-D0WD-V3")
        finally:
            esp._port.close()
            if args.receipt:
                args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result))


if __name__ == "__main__":
    main()
