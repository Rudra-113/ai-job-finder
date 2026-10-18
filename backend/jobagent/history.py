"""Saved searches for the signed-in person. Listings are the ones that search returned."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from jobagent.paths import atomic_write, file_lock, read_json


def _path(home: Path) -> Path:
    return home / "searches.json"


def load_history(home: Path) -> list[dict]:
    data = read_json(_path(home), [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_search(home: Path, query: str, report: dict) -> dict:
    record = {
        "id": hashlib.sha256(f"{query}|{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:12],
        "query": (query or "Saved search")[:240],
        "created": datetime.now(timezone.utc).isoformat(),
        "discovered": report.get("discovered") or report.get("found") or 0,
        "unique": report.get("analyzed") or 0,
        "active": report.get("active") or 0,
        "strong": report.get("qualified") or 0,
        "final_count": report.get("final_count") or 0,
        "source_report": report.get("source_report") or [],
        "opportunities": report.get("opportunities") or [],
    }
    path = _path(home)

    def mutate() -> None:
        rows = load_history(home)
        rows.insert(0, record)
        atomic_write(path, rows[:20])

    with file_lock(path):
        mutate()
    return record


def find_search(home: Path, search_id: str) -> dict | None:
    for row in load_history(home):
        if row.get("id") == search_id:
            return row
    return None
