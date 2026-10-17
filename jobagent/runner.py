"""One search-and-apply pass, then a wait. Submissions stay on this computer."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobagent.apply import apply_to_job, default_headless
from jobagent.filters import screen
from jobagent.logsetup import configure, safe_error
from jobagent.models import ApplyResult, Job
from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.profile import load_profile
from jobagent.search import search_jobs
from jobagent.secrets import load_secrets
from jobagent.settings import load_settings
from jobagent.store import Store
from jobagent.textutil import canonical_url, job_identity, safe_http_url

MAX_APPLICATIONS_PER_PASS = 5
SEARCH_INTERVAL_SECONDS = 30 * 60

logger = logging.getLogger("jobagent")


def state_path(home: Path) -> Path:
    return home / "state.json"


def default_state() -> dict:
    return {
        "running": False,
        "found": 0,
        "rejected": 0,
        "submitted": 0,
        "failed": 0,
        "status_line": "Idle. Nothing is submitted until you start a search.",
        "warnings": [],
        "failures": [],
        "rejection_counts": {},
        "updated_at": "",
    }


def load_state(home: Path) -> dict:
    path = state_path(home)
    with file_lock(path):
        data = read_json(path, {})
    state = default_state()
    if isinstance(data, dict):
        state.update({key: data[key] for key in state if key in data})
    return state


def write_state(home: Path, **changes) -> None:
    path = state_path(home)
    with file_lock(path):
        current = default_state()
        stored = read_json(path, {})
        if isinstance(stored, dict):
            current.update({key: stored[key] for key in current if key in stored})
        current.update(changes)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write(path, current)


def record_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


def make_record(job: Job, score: int, result: ApplyResult) -> dict:
    url = safe_http_url(job.apply_url or job.url)
    return {
        "id": record_id(url or job.url),
        "company": job.company,
        "role": job.title,
        "url": url,
        "url_keys": [canonical_url(job.url), canonical_url(job.apply_url)],
        "identity": job_identity(job),
        "date": datetime.now().astimezone().date().isoformat(),
        "status": result.status,
        "match_score": score,
        "result": result.result,
        "reason": result.reason,
        "source": job.source,
        "submit_clicked": result.submit_clicked,
        "blocks_retry": result.blocks_retry,
        "screenshot": result.screenshot,
    }


def run_cycle(home: Path, stop: threading.Event | None = None) -> None:
    configure(home)
    stop = stop or threading.Event()
    profile = load_profile(home)
    problem = profile.problem()
    if problem:
        write_state(home, status_line=problem, found=0, rejected=0, submitted=0, failed=0, warnings=[], failures=[], rejection_counts={})
        return
    settings = load_settings(home)
    if not settings.sectors or not settings.roles:
        write_state(home, status_line="Enter a target sector and at least one role before searching.")
        return
    write_state(home, status_line="Searching for new listings.", warnings=[], failures=[], rejection_counts={}, found=0, rejected=0, submitted=0, failed=0)
    try:
        jobs, warnings = search_jobs(settings)
    except Exception as exc:
        logger.error("search error: %s", safe_error(exc))
        write_state(home, status_line="Search failed before any application was opened.", warnings=["Search"])
        return
    if stop.is_set():
        write_state(home, status_line="Stopped.", warnings=warnings)
        return
    store = Store(home)
    secrets = load_secrets(home)
    found = rejected = submitted = failed = attempts = 0
    reasons: Counter[str] = Counter()
    failures: list[dict] = []
    hit_limit = False
    for job in jobs:
        if stop.is_set():
            break
        if store.blocks(job):
            continue
        found += 1
        decision = screen(job, settings, profile, store.blocks)
        if not decision.accept:
            rejected += 1
            reasons[decision.reason] += 1
            logger.info("skip %s | %s | %s", job.company, job.title, decision.reason)
            write_state(
                home,
                found=found,
                rejected=rejected,
                submitted=submitted,
                failed=failed,
                warnings=warnings,
                failures=failures,
                rejection_counts=dict(reasons),
                status_line="Checking listings.",
            )
            continue
        if attempts >= MAX_APPLICATIONS_PER_PASS:
            hit_limit = True
            break
        attempts += 1
        logger.info("open %s | %s | score %s", job.company, job.title, decision.score)
        preview = make_record(job, decision.score, ApplyResult("applying", blocks_retry=True))
        store.upsert(preview)
        shot = home / "reviews" / f"{preview['id']}.png"
        started = datetime.now(timezone.utc)

        def reader(domains, started_at=started):
            from jobagent.gmail_otp import fetch_otp

            return fetch_otp(home, domains, started_at)

        try:
            result = apply_to_job(
                job,
                profile,
                secrets,
                home,
                otp_reader=reader,
                headless=default_headless(),
                screenshot_path=shot,
            )
        except Exception as exc:
            logger.error("apply error: %s", safe_error(exc))
            result = ApplyResult(
                "needs_user",
                "",
                "The browser stopped unexpectedly. The application was not retried.",
                True,
                False,
            )
        store.upsert(make_record(job, decision.score, result))
        if result.status == "submitted":
            submitted += 1
            logger.info("submitted %s | %s | score %s", job.company, job.title, decision.score)
        elif result.status == "failed":
            failed += 1
            failures.append({"company": job.company, "role": job.title, "reason": result.reason})
            logger.info("failed %s | %s | %s", job.company, job.title, result.reason)
        else:
            logger.info("paused %s | %s | %s", job.company, job.title, result.reason)
        write_state(
            home,
            found=found,
            rejected=rejected,
            submitted=submitted,
            failed=failed,
            warnings=warnings,
            failures=failures[-10:],
            rejection_counts=dict(reasons),
            status_line="Applying." if not stop.is_set() else "Stopping.",
        )
    if stop.is_set():
        line = "Stopped."
    elif hit_limit:
        line = "Paused new submissions after 5 this pass. Matching listings can continue on the next pass."
    elif submitted:
        line = f"Finished this pass. Submitted {submitted}."
    elif found == 0:
        line = "No new listings in this pass."
    else:
        line = "Finished this pass. No application was submitted."
    if warnings:
        line += " Some sources did not respond: " + ", ".join(warnings) + "."
    write_state(
        home,
        found=found,
        rejected=rejected,
        submitted=submitted,
        failed=failed,
        warnings=warnings,
        failures=failures[-10:],
        rejection_counts=dict(reasons),
        status_line=line,
    )


class AgentService:
    def __init__(self, home: Path):
        self.home = home
        self.stop = threading.Event()
        self.wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self.stop.clear()
            self.wake.clear()
            self._thread = threading.Thread(target=self._loop, name="job-agent", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        self.stop.set()
        self.wake.set()

    def request_cycle(self) -> None:
        self.wake.set()

    def _loop(self) -> None:
        configure(self.home)
        write_state(self.home, running=True, status_line="Searching for new listings.")
        try:
            while not self.stop.is_set():
                try:
                    run_cycle(self.home, self.stop)
                except Exception as exc:
                    logger.error("cycle error: %s", safe_error(exc))
                    write_state(self.home, running=True, status_line="The last pass hit an error. It will try again.")
                if self.stop.is_set():
                    break
                nxt = datetime.now().astimezone() + timedelta(seconds=SEARCH_INTERVAL_SECONDS)
                current = load_state(self.home)
                write_state(self.home, running=True, status_line=f"{current['status_line']} Next search at {nxt:%H:%M}.")
                self.wake.wait(SEARCH_INTERVAL_SECONDS)
                self.wake.clear()
        finally:
            write_state(self.home, running=False, status_line="Stopped.")
