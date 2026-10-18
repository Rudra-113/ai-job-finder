"""Password gate in front of the local job agent.

The local agent listens on port 47321. This process listens only on
127.0.0.1. It asks for a password, then forwards the request with Host
rewritten to that local port and the public name kept in X-Forwarded-Host.
Gmail tokens and the data folder are not files this gate will fetch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import http.client

GATE_HOST = "127.0.0.1"
GATE_PORT = 47322
UPSTREAM_PORT = 47321
USERNAME = "jobagent"
MAX_BODY = 8 * 1024 * 1024

_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "authorization",
}
_BLOCKED = (
    "gmail_token",
    "gmail_client",
    "secret.key",
    "secrets.json",
    "profile.json",
    "applications.json",
    "/data/",
)


def _public_host(headers) -> str:
    """Keep the public tunnel name when the proxy already recorded it."""
    incoming = ""
    for key, value in headers.items():
        if key.lower() == "x-forwarded-host" and "trycloudflare.com" in (value or ""):
            incoming = value.split(",")[0].strip()
            break
    host = (headers.get("Host") or "").split(",")[0].strip()
    if "trycloudflare.com" in host:
        return host
    return incoming or host


def _blocked(path: str) -> bool:
    name = (path or "").split("?", 1)[0].casefold()
    return any(part in name for part in _BLOCKED)


def _gate_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"jobagent-gate-v1", hashlib.sha256).hexdigest()


def _cookie_authorized(header: str, password: str) -> bool:
    expected = _gate_token(password)
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == "jobagent_gate" and hmac.compare_digest(value, expected):
            return True
    return False


def _authorized(header: str, username: str, password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    user, sep, given = decoded.partition(":")
    if not sep:
        return False
    return hmac.compare_digest(user, username) and hmac.compare_digest(given, password)


class GateServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, password: str, upstream_port: int = UPSTREAM_PORT, port: int = GATE_PORT):
        if not password or len(password) < 12:
            raise ValueError("The tunnel password must be at least 12 characters.")
        self.password = password
        self.username = USERNAME
        self.upstream_port = upstream_port
        super().__init__((GATE_HOST, port), GateHandler)

    def server_bind(self):
        super().server_bind()
        host, _port = self.server_address[:2]
        if host not in {GATE_HOST, "localhost"}:
            raise RuntimeError("The password gate refuses to listen on a public address.")


class GateHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: GateServer

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_HEAD(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def log_message(self, fmt, *args):
        # Status only. The request line can contain a CV upload path or a code.
        try:
            status = args[1] if len(args) > 1 else ""
            print(f"gate {self.command} {status}", flush=True)
        except Exception:
            return

    def _unauthorized(self):
        body = b"Sign in required.\n"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Job Agent"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _plain(self, status: int, text: str):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _forward(self):
        password = self.server.password
        via_password = _authorized(self.headers.get("Authorization", ""), self.server.username, password)
        if not via_password and not _cookie_authorized(self.headers.get("Cookie", ""), password):
            self._unauthorized()
            return
        if _blocked(self.path):
            self._plain(404, "Not found.\n")
            return
        length_raw = self.headers.get("Content-Length")
        if self.command in {"POST", "PUT"} and not length_raw:
            self._plain(411, "Content-Length is required.\n")
            return
        try:
            length = int(length_raw or "0")
        except ValueError:
            self._plain(400, "Invalid request.\n")
            return
        if length < 0 or length > MAX_BODY:
            self._plain(413, "The upload is too large.\n")
            return
        body = self.rfile.read(length) if length else b""
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in _HOP and key.lower() not in {"x-forwarded-host", "x-forwarded-proto"}
        }
        public_host = _public_host(self.headers)
        headers["Host"] = f"{GATE_HOST}:{self.server.upstream_port}"
        headers["X-Forwarded-Host"] = public_host
        headers["X-Forwarded-Proto"] = "https" if "trycloudflare.com" in public_host else "http"
        headers["Connection"] = "close"
        try:
            upstream = http.client.HTTPConnection(GATE_HOST, self.server.upstream_port, timeout=120)
            upstream.request(self.command, self.path, body=body if body else None, headers=headers)
            response = upstream.getresponse()
            payload = response.read()
            status = response.status
            forwarded = [
                (key, value)
                for key, value in response.getheaders()
                if key.lower() not in _HOP and key.lower() != "content-length"
            ]
            upstream.close()
        except OSError:
            self._plain(502, "The local job agent is not running.\n")
            return
        self.send_response(status)
        for key, value in forwarded:
            self.send_header(key, value)
        if via_password:
            # The browser sends the password for the page, then omits it on fetch().
            # A cookie keeps those API calls authorized.
            self.send_header(
                "Set-Cookie",
                f"jobagent_gate={_gate_token(password)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=43200",
            )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)


def serve(password: str, upstream_port: int = UPSTREAM_PORT, port: int = GATE_PORT) -> None:
    server = GateServer(password, upstream_port=upstream_port, port=port)
    print(f"Password gate: http://{GATE_HOST}:{server.server_address[1]} -> http://{GATE_HOST}:{upstream_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    secret = os.environ.get("JOBAGENT_TUNNEL_PASSWORD", "").strip()
    if len(secret) < 12:
        raise SystemExit("The password gate is started by start_tunnel.py.")
    serve(secret)
