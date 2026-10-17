import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tunnel_gate import USERNAME, GateServer, _authorized, _blocked


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        self._reply()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.server.body = self.rfile.read(length)
        self._reply()

    def _reply(self):
        body = f"host={self.headers.get('Host')}\nauth={self.headers.get('Authorization')}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _fmt, *_args):
        return


def _basic(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def test_password_compare_and_blocked_files():
    assert _authorized(_basic(USERNAME, "correct-password"), USERNAME, "correct-password")
    assert not _authorized(_basic(USERNAME, "wrong-password-1"), USERNAME, "correct-password")
    assert not _authorized("", USERNAME, "correct-password")
    assert _blocked("/data/gmail_token.json")
    assert _blocked("/profile.json")
    assert not _blocked("/profile")
    assert not _blocked("/")


def test_gate_requires_password_and_rewrites_host():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream.body = b""
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    gate = GateServer("long-enough-password", upstream_port=upstream.server_address[1], port=0)
    gate_thread = threading.Thread(target=gate.serve_forever, daemon=True)
    gate_thread.start()
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{gate.server_address[1]}/profile"
    try:
        denied = urllib.request.urlopen(url, timeout=3)
        raise AssertionError(denied.status)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
        assert b"Ada" not in exc.read()
    request = urllib.request.Request(url, data=b"hello", method="POST")
    request.add_header("Authorization", _basic(USERNAME, "long-enough-password"))
    with urllib.request.urlopen(request, timeout=3) as response:
        text = response.read().decode()
    assert f"host=127.0.0.1:{upstream.server_address[1]}" in text
    assert "auth=None" in text
    assert upstream.body == b"hello"
    blocked = urllib.request.Request(
        f"http://127.0.0.1:{gate.server_address[1]}/data/gmail_token.json",
        headers={"Authorization": _basic(USERNAME, "long-enough-password")},
    )
    try:
        urllib.request.urlopen(blocked, timeout=3)
        raise AssertionError("token path was forwarded")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    finally:
        gate.shutdown()
        upstream.shutdown()
