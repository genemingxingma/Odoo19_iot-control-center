#!/usr/bin/env python3
import http.client
import os
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


BIND_HOST = os.environ.get("OTA_PROXY_BIND", "192.168.10.15")
BIND_PORT = int(os.environ.get("OTA_PROXY_PORT", "8443"))
UPSTREAM_HOST = os.environ.get("OTA_UPSTREAM_HOST", "192.168.10.15")
UPSTREAM_PORT = int(os.environ.get("OTA_UPSTREAM_PORT", "8069"))
CERT_FILE = os.environ.get("OTA_CERT_FILE", "/etc/iot-ota-proxy/server.crt")
KEY_FILE = os.environ.get("OTA_KEY_FILE", "/etc/iot-ota-proxy/server.key")
FIRMWARE_PATH = re.compile(r"^/f/[1-9][0-9]*$")


class OtaProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "IoT-OTA-Proxy"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Never write device tokens from the query string to the journal.
        safe_path = urlsplit(self.path).path
        print(f'{self.client_address[0]} "{self.command} {safe_path}"', flush=True)

    def _reply(self, status, body, content_type="text/plain; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._reply(200, "ok")
            return
        if not FIRMWARE_PATH.fullmatch(parsed.path):
            self._reply(404, "not found")
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        if not all(query.get(key, [""])[0] for key in ("s", "t", "db")):
            self._reply(404, "not found")
            return

        upstream = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=30)
        try:
            upstream.request(
                "GET",
                self.path,
                headers={"Host": UPSTREAM_HOST, "User-Agent": "IoT-LAN-OTA-Proxy/1.0"},
            )
            response = upstream.getresponse()
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Content-Disposition"):
                value = response.getheader(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while chunk := response.read(64 * 1024):
                self.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            self._reply(502, "upstream unavailable")
        finally:
            upstream.close()


def main():
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), OtaProxyHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
