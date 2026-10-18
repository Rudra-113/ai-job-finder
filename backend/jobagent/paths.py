"""Local files only. Writes are atomic and locked inside this process."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_home() -> Path:
    env = os.environ.get("DATA_DIR") or os.environ.get("JOBAGENT_HOME")
    if env:
        return Path(env).expanduser()
    return project_root() / "data"


def file_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_secret_key(path: Path) -> str:
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    import secrets

    key = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key
