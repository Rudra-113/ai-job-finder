"""API key for grounded answers. The key stays in the local data folder."""

from __future__ import annotations

import os
from pathlib import Path

from jobagent.models import Secrets
from jobagent.paths import atomic_write, file_lock, read_json


def secrets_path(home: Path) -> Path:
    return home / "secrets.json"


def load_secrets(home: Path) -> Secrets:
    path = secrets_path(home)
    with file_lock(path):
        data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    return Secrets(
        api_key=str(data.get("api_key") or os.environ.get("OPENAI_API_KEY") or os.environ.get("XAI_API_KEY") or ""),
        api_base=str(data.get("api_base") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"),
        api_model=str(data.get("api_model") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"),
    )


def stored_secrets(home: Path) -> dict:
    data = read_json(secrets_path(home), {})
    return data if isinstance(data, dict) else {}


def save_secret_values(home: Path, api_key: str, api_base: str, api_model: str) -> None:
    path = secrets_path(home)
    with file_lock(path):
        atomic_write(path, {"api_key": api_key, "api_base": api_base, "api_model": api_model})
        try:
            path.chmod(0o600)
        except OSError:
            pass


def update_secrets_from_form(home: Path, form) -> str | None:
    current = stored_secrets(home)
    if form.get("clear_api_key"):
        api_key = ""
    elif (form.get("api_key") or "").strip():
        api_key = form.get("api_key").strip()
    else:
        api_key = str(current.get("api_key") or "")
    api_base = (form.get("api_base") or "").strip() or "https://api.openai.com/v1"
    api_model = (form.get("api_model") or "").strip() or "gpt-4o-mini"
    if not (
        api_base.startswith("https://")
        or api_base.startswith("http://127.0.0.1")
        or api_base.startswith("http://localhost")
    ):
        return "Use an https API URL, or a local http://127.0.0.1 address."
    save_secret_values(home, api_key, api_base, api_model)
    return None


def api_key_is_set(home: Path) -> bool:
    return bool(load_secrets(home).api_key)
