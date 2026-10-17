"""Stop the temporary Cloudflare tunnel and the password gate.

The job agent on 127.0.0.1:47321 keeps running.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("JOBAGENT_HOME", ROOT / "data"))


def _read_pid(name: str) -> int:
    path = HOME / name
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _stop(name: str) -> None:
    path = HOME / name
    pid = _read_pid(name)
    if pid <= 0:
        print(f"No saved process for {name}.")
        path.unlink(missing_ok=True)
        return
    try:
        if os.name != "nt":
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"Stopped process {pid} ({name}).")
    except OSError as exc:
        print(f"Process {pid} was not running ({exc}).")
    path.unlink(missing_ok=True)


def main() -> None:
    _stop("cloudflared.pid")
    _stop("tunnel_gate.pid")
    print("Tunnel closed. The job agent is still on http://127.0.0.1:47321 if you started it separately.")


if __name__ == "__main__":
    main()
