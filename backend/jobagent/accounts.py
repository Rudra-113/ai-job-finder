"""Per-person storage. One Google account cannot read another account's files."""

from __future__ import annotations

import re
from pathlib import Path


def safe_user_id(user_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", user_id or "")[:80]
    return cleaned or "unknown"


def workspace_id(root: Path, email: str, sub: str) -> str:
    """A Gmail address that matches the saved profile opens that profile."""
    from jobagent.profile import load_profile

    wanted = (email or "").strip().casefold()
    saved = load_profile(root).email.strip().casefold()
    if wanted and saved and wanted == saved:
        return "local"
    return sub


def user_home(root: Path, user_id: str) -> Path:
    """The original computer workspace stays at the data root. Other people get a private folder."""
    if user_id == "local":
        return root
    path = root / "users" / safe_user_id(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
