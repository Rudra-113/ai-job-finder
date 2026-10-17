"""Start a temporary Cloudflare Quick Tunnel in front of the password gate.

The job agent is not deployed. cloudflared publishes only 127.0.0.1:47322,
and that gate forwards to the agent on 127.0.0.1:47321 after a password.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tunnel_gate import GATE_HOST, GATE_PORT, UPSTREAM_PORT, USERNAME

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("JOBAGENT_HOME", ROOT / "data"))
URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def password_path() -> Path:
    return HOME / "tunnel_password"


def load_or_create_password() -> str:
    env = os.environ.get("JOBAGENT_TUNNEL_PASSWORD", "").strip()
    if env:
        if len(env) < 12:
            raise SystemExit("JOBAGENT_TUNNEL_PASSWORD must be at least 12 characters.")
        return env
    path = password_path()
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 12:
            return value
    value = secrets.token_urlsafe(18)
    HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def cloudflared_bin() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    names = ["cloudflared.exe", "cloudflared"] if os.name == "nt" else ["cloudflared"]
    candidates = [Path.home() / ".local" / "bin" / name for name in names]
    candidates.append(ROOT / "bin" / names[0])
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def agent_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://{GATE_HOST}:{UPSTREAM_PORT}/", timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start_gate(password: str) -> None:
    pid_path = HOME / "tunnel_gate.pid"
    if _pid_alive(_read_pid(pid_path)):
        print(f"Password gate is already running on http://{GATE_HOST}:{GATE_PORT}")
        return
    log_path = HOME / "tunnel_gate.log"
    HOME.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "a", encoding="utf-8")
    env = os.environ.copy()
    env["JOBAGENT_TUNNEL_PASSWORD"] = password
    popen = {"cwd": str(ROOT), "stdout": log, "stderr": subprocess.STDOUT, "env": env}
    if os.name == "nt":
        popen["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, str(ROOT / "tunnel_gate.py")], **popen)
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(30):
        if not _pid_alive(proc.pid):
            raise SystemExit(f"The password gate stopped. See {log_path}")
        try:
            urllib.request.urlopen(f"http://{GATE_HOST}:{GATE_PORT}/", timeout=1)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 404}:
                print(f"Password gate: http://{GATE_HOST}:{GATE_PORT} -> http://{GATE_HOST}:{UPSTREAM_PORT}")
                return
        except OSError:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    raise SystemExit(f"The password gate did not open. See {log_path}")


def start_cloudflared(binary: str) -> str:
    pid_path = HOME / "cloudflared.pid"
    log_path = HOME / "cloudflared.log"
    old = _read_pid(pid_path)
    if _pid_alive(old) and log_path.is_file():
        found = URL_RE.findall(log_path.read_text(encoding="utf-8", errors="replace"))
        if found:
            print("Cloudflare tunnel is already running.")
            return found[-1]
    log = open(log_path, "w", encoding="utf-8")
    popen = {"cwd": str(ROOT), "stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        popen["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen["start_new_session"] = True
    proc = subprocess.Popen(
        [binary, "tunnel", "--url", f"http://{GATE_HOST}:{GATE_PORT}", "--no-autoupdate"],
        **popen,
    )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(60):
        if not _pid_alive(proc.pid):
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
            raise SystemExit(f"cloudflared stopped.\n{detail}")
        text = log_path.read_text(encoding="utf-8", errors="replace")
        found = URL_RE.findall(text)
        if found:
            return found[-1]
        time.sleep(0.5)
    raise SystemExit(f"No public URL yet. See {log_path}")


def main() -> None:
    if not agent_is_up():
        raise SystemExit(
            "The job agent is not running. Start it first with run.bat or: python app.py\n"
            f"It must be on http://{GATE_HOST}:{UPSTREAM_PORT}"
        )
    binary = cloudflared_bin()
    if not binary:
        raise SystemExit(
            "cloudflared is not installed.\n"
            "Windows: winget install --id Cloudflare.cloudflared\n"
            "Then open a new Command Prompt and run this script again."
        )
    password = load_or_create_password()
    start_gate(password)
    url = start_cloudflared(binary)
    print()
    print(f"Public HTTPS URL: {url}")
    print(f"Forwards to: http://{GATE_HOST}:{UPSTREAM_PORT} after the password gate on port {GATE_PORT}")
    print(f"Username: {USERNAME}")
    print(f"Password: {password}")
    print("The local page http://127.0.0.1:47321 does not ask for this password.")
    print("Close the tunnel with: python stop_tunnel.py")
    print("Closing it leaves the job agent running.")


if __name__ == "__main__":
    main()
