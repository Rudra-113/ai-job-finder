"""Application log. A job that may already have been sent is not opened again."""

from __future__ import annotations

from pathlib import Path

from jobagent.models import Job
from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.textutil import canonical_url, duplicate_key, job_identity


class Store:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / "applications.json"

    def records(self) -> list[dict]:
        with file_lock(self.path):
            return self._read()

    def _read(self) -> list[dict]:
        data = read_json(self.path, [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _mutate(self, fn) -> None:
        with file_lock(self.path):
            records = self._read()
            fn(records)
            atomic_write(self.path, records)

    def upsert(self, record: dict) -> None:
        def mutate(records: list[dict]) -> None:
            records[:] = [item for item in records if item.get("id") != record.get("id")]
            records.append(record)

        self._mutate(mutate)

    def blocks(self, job: Job) -> bool:
        keys = {key for key in (canonical_url(job.url), canonical_url(job.apply_url)) if key}
        identity = job_identity(job)
        title_key = duplicate_key(job)
        for record in self.records():
            if not record.get("blocks_retry"):
                continue
            recorded = {canonical_url(key) for key in record.get("url_keys") or [] if key}
            if record.get("url"):
                recorded.add(canonical_url(record["url"]))
            recorded.discard("")
            if keys & recorded:
                return True
            if identity and record.get("identity") == identity:
                return True
            if title_key and record.get("title_key") == title_key:
                return True
        return False

    def recover(self) -> None:
        def mutate(records: list[dict]) -> None:
            for record in records:
                if record.get("status") == "applying":
                    record["status"] = "needs_user"
                    record["blocks_retry"] = True
                    record["reason"] = "The previous attempt stopped unexpectedly and was not retried."

        self._mutate(mutate)

    def clear_block(self, record_id: str) -> bool:
        found = False

        def mutate(records: list[dict]) -> None:
            nonlocal found
            for record in records:
                if record.get("id") == record_id and record.get("status") == "needs_user":
                    record["status"] = "cleared"
                    record["blocks_retry"] = False
                    record["reason"] = "Cleared to try again. Safety checks still apply."
                    found = True

        self._mutate(mutate)
        return found

    def dismiss(self, record_id: str) -> bool:
        found = False

        def mutate(records: list[dict]) -> None:
            nonlocal found
            for record in records:
                if record.get("id") == record_id and record.get("status") == "needs_user":
                    record["status"] = "dismissed"
                    record["blocks_retry"] = True
                    record["reason"] = "You chose not to apply."
                    found = True

        self._mutate(mutate)
        return found
