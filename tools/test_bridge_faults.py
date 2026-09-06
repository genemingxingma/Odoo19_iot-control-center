"""Linux-only bridge smoke/fault test; all listeners and targets use loopback.

Run in a disposable container with python3, mosquitto and a small /faultdisk
tmpfs. Pass the candidate Linux executable as argv[1]. No production config,
database, MQTT credentials or physical devices are used.
"""
import errno
import http.server
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request


def wait_until(predicate, label, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("timeout: " + label)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


mode = "unavailable"
received = {}
attempts = 0


class OdooStub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        global attempts
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        status = 200
        if self.path.endswith("openwrt_inventory"):
            result = {"ok": True, "items": []}
        else:
            attempts += 1
            status = 503 if mode == "unavailable" else 400 if mode == "reject" else 200
            event_id = data["event_id"]
            result = {"ok": True, "event_id": "wrong" if mode == "wrong_receipt" else event_id}
            if mode == "accept":
                previous = received.setdefault(event_id, data)
                assert previous == data, "retry changed the event body"
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def mqtt_publish(port, payload):
    def packet(kind, body):
        length = len(body)
        encoded = bytearray()
        while True:
            digit = length % 128
            length //= 128
            encoded.append(digit | (128 if length else 0))
            if not length:
                return bytes([kind]) + encoded + body

    def string(value):
        value = value.encode()
        return struct.pack("!H", len(value)) + value

    def exact(sock, size):
        data = b""
        while len(data) < size:
            block = sock.recv(size - len(data))
            assert block, "MQTT connection closed"
            data += block
        return data

    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(packet(0x10, string("MQTT") + b"\x04\x02\x00\x3c" + string("fault-fixture")))
        assert exact(sock, 4) == b"\x20\x02\x00\x00"
        sock.sendall(packet(0x32, string("fixture/relay/test/status") + b"\x00\x01" + json.dumps(payload).encode()))
        assert exact(sock, 4) == b"\x40\x02\x00\x01"
        sock.sendall(b"\xe0\x00")


def main():
    global mode
    assert sys.platform == "linux", "disposable Linux container required"
    root = Path("/faultdisk")
    assert root.is_mount() and not list(root.iterdir()), "empty dedicated /faultdisk mount required"
    mqtt_port, tcp_port, api_port = free_port(), free_port(), free_port()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OdooStub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    process = broker = None
    environment = {"PATH": os.environ["PATH"], "RUST_LOG": "error",
        "IOT_BRIDGE_TOKEN": secrets.token_hex(32),
        "IOT_BRIDGE_API_LISTEN": f"127.0.0.1:{api_port}",
        "IOT_BRIDGE_TH_TCP_LISTEN": f"127.0.0.1:{tcp_port}",
        "IOT_BRIDGE_MQTT_HOST": "127.0.0.1", "IOT_BRIDGE_MQTT_PORT": str(mqtt_port),
        "IOT_BRIDGE_MQTT_CLIENT_ID": "iot-v2-fault-fixture", "IOT_BRIDGE_MQTT_TOPIC_ROOT": "fixture/relay",
        "IOT_BRIDGE_ODOO_BASE_URL": f"http://127.0.0.1:{httpd.server_port}",
        "IOT_BRIDGE_QUEUE_PATH": str(root / "outbox")}

    def start_broker():
        return subprocess.Popen([shutil.which("mosquitto"), "-p", str(mqtt_port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start_bridge():
        return subprocess.Popen([sys.argv[1]], env=environment,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def health():
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{api_port}/healthz", data=b"{}")
            with urllib.request.urlopen(request, timeout=1) as response:
                return json.load(response)
        except (OSError, ValueError):
            return {}

    def pending():
        return list((root / "outbox/pending").glob("*.json"))

    def send(n):
        with socket.create_connection(("127.0.0.1", tcp_port), timeout=5) as sock:
            sock.sendall((json.dumps({"fixture_n": n}) + "\n").encode())

    try:
        broker = start_broker()
        process = start_bridge()
        wait_until(lambda: health().get("mqtt_connected"), "initial MQTT connection")
        start = time.monotonic()
        for n in range(300):
            send(n)
        wait_until(lambda: len(pending()) == 300, "durable ingress during HTTP failure")
        snapshot = {path.name: path.read_bytes() for path in pending()}
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=5)
        assert {path.name: path.read_bytes() for path in pending()} == snapshot
        mode = "wrong_receipt"
        before = attempts
        process = start_bridge()
        wait_until(lambda: attempts > before, "forward after forced restart")
        time.sleep(1)
        assert len(pending()) == 300, "wrong receipt deleted a durable event"
        mode = "accept"
        wait_until(lambda: not pending() and len(received) == 300, "replay drain", seconds=90)
        assert set(snapshot) == {event_id + ".json" for event_id in received}
        print(f"PASS restart, wrong ACK and 300-event recovery ({time.monotonic() - start:.1f}s)", flush=True)

        mode = "reject"
        send(10000)
        wait_until(lambda: len(list((root / "outbox/rejected").glob("*.json"))) == 1, "permanent rejection archive")
        assert not pending()
        print("PASS permanent rejection preserved", flush=True)
        mode = "accept"

        mqtt_publish(mqtt_port, {"fixture": "before-disconnect"})
        wait_until(lambda: len(received) == 301, "MQTT ingest before disconnect")
        broker.terminate()
        broker.wait(timeout=5)
        wait_until(lambda: health().get("mqtt_connected") is False, "MQTT loss reported")
        broker = start_broker()
        wait_until(lambda: health().get("mqtt_connected"), "MQTT reconnect")
        time.sleep(1)  # ConnAck precedes subscription acknowledgement.
        mqtt_publish(mqtt_port, {"fixture": "after-reconnect"})
        wait_until(lambda: len(received) == 302 and not pending(), "MQTT ingest and durable ACK after reconnect")
        print("PASS real Mosquitto disconnect/reconnect and resubscribe", flush=True)

        filler = root / "filler"
        with filler.open("wb", buffering=0) as stream:
            try:
                while True:
                    stream.write(b"x" * 65536)
            except OSError as error:
                assert error.errno == errno.ENOSPC
        assert os.statvfs(root).f_bavail == 0, "fault filesystem was not full"
        send(10001)
        wait_until(lambda: health().get("ingress_persistence_failures", 0) > 0, "disk full backpressure")
        assert len(received) == 302
        filler.unlink()
        wait_until(lambda: len(received) == 303 and not pending(), "disk recovery")
        print("PASS real ENOSPC preserves retry and recovers after space returns", flush=True)
        print("IOT_V2_BRIDGE_FAULT_TESTS_OK", flush=True)
    except Exception:
        print("FAULT_DIAGNOSTIC", json.dumps({"health": health(), "pending": len(pending()),
            "accepted_events": len(received), "free_blocks": os.statvfs(root).f_bavail,
            "bridge_exit": process.poll() if process else None}), flush=True)
        raise
    finally:
        for child in (process, broker):
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        httpd.shutdown()


if __name__ == "__main__":
    main()
