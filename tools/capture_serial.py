"""Capture bounded raw serial diagnostics without toggling reset lines."""
import argparse
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", required=True, type=int)
    parser.add_argument("--seconds", required=True, type=int)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        raise RuntimeError("Capture duration must be between 1 and 600 seconds")

    stream = serial.Serial(port=None, baudrate=args.baud, timeout=0.2)
    stream.dtr = False
    stream.rts = False
    stream.port = args.port
    stream.open()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            data = stream.read(4096)
            if data:
                print(data.decode("utf-8", errors="backslashreplace"), end="", flush=True)
    finally:
        stream.close()


if __name__ == "__main__":
    main()
