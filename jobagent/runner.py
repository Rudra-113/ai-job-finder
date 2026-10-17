"""Continuous search. Qualified jobs are applied one at a time.

Automatic mode submits a form when every required field can be filled from the
profile. Review mode leaves the form open for Submit. A blocked application is
recorded and the next qualified job starts.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jobagent.apply import ApplicationSession, default_headless
from jobagent.criteria import compensation_label, infer_workplace
from jobagent.filters import screen
from jobagent.logsetup import configure, safe_error
from jobagent.models import ApplyResult, Job
from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.profile import load_profile
from jobagent.search import search_jobs, search_queries
from jobagent.secrets import load_secrets
from jobagent.settings import load_settings
from jobagent.store import Store
from jobagent.textutil import canonical_url, duplicate_key, job_identity, safe_http_url

logger = logging.getLogger("jobagent")


def state_path(home: Path) -> Path:
    return home / "state.json"


def default_state() -> dict:
    return {
        "running": False,
        "search_status": "stopped",
        "found": 0,
        "rejected": 0,
        "qualified": 0,
        "needs_review": 0,
        "filled": 0,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
        "status_line": "Stopped. Qualified jobs are submitted automatically unless review mode is on.",
        "warnings": [],
        "failures": [],
        "rejection_counts": {},
        "current": None,
        "queue_size": 0,
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
    posted = ""
    if job.posted_at is not None:
        posted = job.posted_at.date().isoformat()
    return {
        "id": record_id(url or job.url),
        "company": job.company,
        "role": job.title,
        "url": url,
        "url_keys": [canonical_url(job.url), canonical_url(job.apply_url)],
        "identity": job_identity(job),
        "title_key": duplicate_key(job),
        "date": datetime.now().astimezone().date().isoformat(),
        "found_at": datetime.now(timezone.utc).isoformat(),
        "posted": posted,
        "status": result.status,
        "match_score": score,
        "compensation": compensation_label(job),
        "location": job.location,
        "remote": infer_workplace(job),
        "result": result.result,
        "reason": result.reason,
        "source": job.source,
        "submit_clicked": result.submit_clicked,
        "blocks_retry": result.blocks_retry,
        "screenshot": result.screenshot,
        "filled": list(result.filled),
        "answered": list(result.answered),
        "needs_input": list(result.needs_input),
        "resume": "",
        "submitted_at": "",
    }


def _current_view(record: dict) -> dict:
    return {
        "id": record.get("id") or "",
        "company": record.get("company") or "",
        "role": record.get("role") or "",
        "url": record.get("url") or "",
        "match_score": record.get("match_score") or 0,
        "compensation": record.get("compensation") or "unknown",
        "location": record.get("location") or "",
        "posted": record.get("posted") or "",
        "remote": record.get("remote") or "",
        "filled": record.get("filled") or [],
        "answered": record.get("answered") or [],
        "needs_input": record.get("needs_input") or [],
        "screenshot": record.get("screenshot") or "",
        "status": record.get("status") or "",
    }


def _counts(found, rejected, qualified, needs_review, filled, submitted, skipped, failed, reasons, failures, warnings, queue) -> dict:
    return {
        "found": found,
        "rejected": rejected,
        "qualified": qualified,
        "needs_review": needs_review,
        "filled": filled,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
        "rejection_counts": dict(reasons),
        "failures": failures[-10:],
        "warnings": warnings,
        "queue_size": len(queue),
    }


def next_queries(settings, cursor: list[int]) -> list[str]:
    queries = search_queries(settings)
    if not queries:
        return []
    start = cursor[0] % len(queries)
    window = [queries[(start + offset) % len(queries)] for offset in range(min(3, len(queries)))]
    cursor[0] = start + 3
    return window


def open_application(job, profile, secrets, home, otp_reader, headless, screenshot_path, session: ApplicationSession | None = None, preview: bool = False):
    holder = session or ApplicationSession()
    return holder.open_and_fill(job, profile, secrets, home, otp_reader, headless, screenshot_path, preview=preview)


def job_from_record(record: dict) -> Job:
    url = record.get("url") or ""
    return Job(
        source=str(record.get("source") or "queue"),
        company=str(record.get("company") or ""),
        title=str(record.get("role") or ""),
        url=url,
        apply_url=url,
        location=str(record.get("location") or ""),
        workplace=str(record.get("remote") or "unknown"),
    )


def load_queued(home: Path) -> list[tuple[Job, int]]:
    pending: list[tuple[Job, int]] = []
    for record in Store(home).records():
        if record.get("status") != "queued" or not record.get("url"):
            continue
        try:
            score = int(record.get("match_score") or 0)
        except (TypeError, ValueError):
            score = 0
        pending.append((job_from_record(record), score))
    return pending


def run_cycle(
    home: Path,
    stop: threading.Event | None = None,
    session: ApplicationSession | None = None,
    queue: list | None = None,
    cursor: list[int] | None = None,
    totals: dict | None = None,
) -> None:
    configure(home)
    stop = stop or threading.Event()
    session = session or ApplicationSession()
    queue = queue if queue is not None else []
    cursor = cursor if cursor is not None else [0]
    profile = load_profile(home)
    problem = profile.problem()
    if problem:
        write_state(home, status_line=problem, search_status="running" if totals else "stopped")
        return
    settings = load_settings(home)
    if not settings.sectors or not settings.roles:
        write_state(home, status_line="Enter a target sector and at least one role before searching.")
        return
    numbers = totals if totals is not None else {
        "found": 0,
        "rejected": 0,
        "qualified": 0,
        "needs_review": 0,
        "filled": 0,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
    }
    reasons: Counter[str] = Counter(load_state(home).get("rejection_counts") or {})
    failures = list(load_state(home).get("failures") or [])
    if queue and not session.is_open():
        job, score = queue.pop(0)
        _fill(home, job, score, profile, session, numbers, reasons, failures, [], queue, stop)
        return
    write_state(
        home,
        search_status="running",
        status_line="Searching public listings.",
        queue_size=len(queue),
        **{key: numbers[key] for key in ("found", "rejected", "qualified", "needs_review", "filled", "submitted", "skipped", "failed")},
    )
    try:
        jobs, warnings = search_jobs(settings, next_queries(settings, cursor))
    except Exception as exc:
        logger.error("search error: %s", safe_error(exc))
        write_state(home, status_line="Search failed before any application was opened.", warnings=["Search"])
        return
    if stop.is_set():
        write_state(home, status_line="Stopped.", warnings=warnings)
        return
    store = Store(home)
    opened = False
    for job in jobs:
        if stop.is_set():
            break
        if store.blocks(job):
            continue
        numbers["found"] += 1
        decision = screen(job, settings, profile, store.blocks)
        if not decision.accept:
            numbers["rejected"] += 1
            reasons[decision.reason] += 1
            logger.info("skip %s | %s | %s | %s", job.source, job.company, job.title, decision.reason)
            store.upsert(make_record(job, decision.score, ApplyResult("rejected", "", decision.reason, True, False)))
            continue
        numbers["qualified"] += 1
        logger.info("qualify %s | %s | score %s | pay %s | queued", job.company, job.title, decision.score, compensation_label(job))
        store.upsert(make_record(job, decision.score, ApplyResult("queued", "Waiting to apply.", "", True, False)))
        if opened or session.is_open():
            queue.append((job, decision.score))
            continue
        opened = True
        _fill(home, job, decision.score, profile, session, numbers, reasons, failures, warnings, queue, stop)
    if not session.is_open():
        write_state(
            home,
            search_status="running",
            status_line="Searching public listings." if not opened else load_state(home).get("status_line") or "Searching public listings.",
            **_counts(
                numbers["found"], numbers["rejected"], numbers["qualified"], numbers["needs_review"],
                numbers["filled"], numbers["submitted"], numbers["skipped"], numbers["failed"],
                reasons, failures, warnings, queue,
            ),
        )
    else:
        write_state(
            home,
            **_counts(
                numbers["found"], numbers["rejected"], numbers["qualified"], numbers["needs_review"],
                numbers["filled"], numbers["submitted"], numbers["skipped"], numbers["failed"],
                reasons, failures, warnings, queue,
            ),
        )


def _otp(home: Path, started):
    def reader(domains, started_at=started):
        from jobagent.gmail_otp import fetch_otp

        return fetch_otp(home, domains, started_at)

    return reader


def _log_attempt(job: Job, result: ApplyResult, resume: str) -> None:
    url = safe_http_url(job.apply_url or job.url)
    if result.status == "submitted":
        logger.info("submitted %s | %s | %s | resume %s | %s", job.company, job.title, url, resume or "none", result.result)
        return
    logger.info(
        "not submitted %s | %s | %s | %s | %s",
        result.status,
        job.company,
        job.title,
        url,
        result.reason or result.result or "no reason recorded",
    )


def _fill(home, job, score, profile, session, numbers, reasons, failures, warnings, queue, stop) -> None:
    if stop.is_set():
        return
    secrets = load_secrets(home)
    settings = load_settings(home)
    manual = bool(settings.manual_review)
    store = Store(home)
    preview = make_record(job, score, ApplyResult("applying", "Opening the application.", "", True, False))
    resume = Path(profile.cv_path).name if profile.cv_path else ""
    preview["resume"] = resume
    store.upsert(preview)
    shot = home / "reviews" / f"{preview['id']}.png"
    started = datetime.now(timezone.utc)
    write_state(
        home,
        search_status="running",
        status_line=f"Applying to {job.company} — {job.title}.",
        current=_current_view(preview),
        queue_size=len(queue),
    )
    try:
        result = open_application(
            job,
            profile,
            secrets,
            home,
            _otp(home, started),
            default_headless(),
            shot,
            session,
            preview=manual,
        )
    except Exception as exc:
        logger.error("apply error: %s", safe_error(exc))
        result = ApplyResult("needs_user", "", "The browser stopped unexpectedly. Nothing was submitted.", True, False)
    record = make_record(job, score, result)
    record["id"] = preview["id"]
    record["resume"] = resume
    if result.status == "submitted":
        record["submitted_at"] = datetime.now(timezone.utc).isoformat()
    store.upsert(record)
    if result.status == "filled" and manual:
        _log_attempt(job, result, resume)
        numbers["filled"] += 1
        write_state(
            home,
            search_status="paused",
            status_line="Review mode: the form is filled and waiting for Submit or Skip.",
            current=_current_view(record),
            **_counts(
                numbers["found"], numbers["rejected"], numbers["qualified"], numbers["needs_review"],
                numbers["filled"], numbers["submitted"], numbers["skipped"], numbers["failed"],
                reasons, failures, warnings, queue,
            ),
        )
        return
    if result.status == "filled":
        result = ApplyResult(
            "needs_user",
            "",
            "The form was filled but submission was not confirmed.",
            True,
            False,
            filled=result.filled,
            answered=result.answered,
            needs_input=result.needs_input,
        )
        record = make_record(job, score, result)
        record["id"] = preview["id"]
        record["resume"] = resume
        store.upsert(record)
    _log_attempt(job, result, resume)
    if result.status == "submitted":
        numbers["filled"] += 1
        numbers["submitted"] += 1
        line = f"Submitted {job.company} — {job.title}. Next qualified job is next."
    elif result.status == "skipped":
        numbers["skipped"] += 1
        line = f"Skipped {job.company}: {result.reason}"
    elif result.status == "failed":
        numbers["failed"] += 1
        failures.append({"company": job.company, "role": job.title, "reason": result.reason})
        line = f"Failed {job.company}: {result.reason}"
    else:
        numbers["needs_review"] += 1
        line = f"Needs review {job.company}: {result.reason}"
    write_state(
        home,
        search_status="running",
        status_line=line,
        current=None,
        **_counts(
            numbers["found"], numbers["rejected"], numbers["qualified"], numbers["needs_review"],
            numbers["filled"], numbers["submitted"], numbers["skipped"], numbers["failed"],
            reasons, failures, warnings, queue,
        ),
    )


class AgentService:
    def __init__(self, home: Path):
        self.home = home
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.action = threading.Event()
        self._choice = ""
        self._answers: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.session = ApplicationSession()
        self.queue: list = []
        self.cursor = [0]
        self.totals = {
            "found": 0,
            "rejected": 0,
            "qualified": 0,
            "needs_review": 0,
            "filled": 0,
            "submitted": 0,
            "skipped": 0,
            "failed": 0,
        }

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self.stop.clear()
            self.wake.clear()
            self.action.clear()
            self.queue.clear()
            self.queue.extend(load_queued(self.home))
            self.cursor[0] = 0
            for key in self.totals:
                self.totals[key] = 0
            self.totals["qualified"] = len(self.queue)
            self._thread = threading.Thread(target=self._loop, name="job-agent", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        self.stop.set()
        self.wake.set()
        self.action.set()

    def request_cycle(self) -> None:
        self.wake.set()

    def request_submit(self) -> None:
        self._choice = "submit"
        self.action.set()

    def request_skip(self) -> None:
        self._choice = "skip"
        self.action.set()

    def request_edit(self, answers: dict[str, str]) -> None:
        self._answers = dict(answers)
        self._choice = "edit"
        self.action.set()

    def _take_choice(self) -> tuple[str, dict]:
        choice = self._choice
        answers = dict(self._answers)
        self._choice = ""
        self._answers = {}
        self.action.clear()
        return choice, answers

    def _resolve(self, choice: str, answers: dict) -> None:
        state = load_state(self.home)
        current = state.get("current") or {}
        record_id = current.get("id") or ""
        store = Store(self.home)
        if choice == "edit" and self.session.is_open():
            result = self.session.apply_answers(answers)
            records = store.records()
            for record in records:
                if record.get("id") == record_id:
                    record["filled"] = result.filled
                    record["answered"] = result.answered
                    record["needs_input"] = result.needs_input
                    record["status"] = "filled"
                    store.upsert(record)
                    current = _current_view(record)
                    break
            write_state(self.home, search_status="paused", current=current, status_line="Updated the open form. Nothing was submitted.")
            return
        if choice == "submit" and self.session.is_open():
            result = self.session.submit()
        elif choice == "skip":
            self.session.close()
            result = ApplyResult("skipped", "You skipped this application. Nothing was submitted.", "", True, False)
        else:
            self.session.close()
            result = ApplyResult("needs_user", "", "Stopped before submit. Nothing was submitted.", True, False)
        records = store.records()
        target = next((item for item in records if item.get("id") == record_id), None)
        if target is not None:
            target["status"] = result.status
            target["result"] = result.result
            target["reason"] = result.reason
            target["submit_clicked"] = result.submit_clicked
            target["blocks_retry"] = True
            store.upsert(target)
        if result.status == "submitted":
            self.totals["submitted"] += 1
            line = "Submitted. Searching for the next job."
        elif result.status == "skipped":
            self.totals["skipped"] += 1
            line = "Skipped. Searching for the next job."
        else:
            self.totals["needs_review"] += 1
            line = result.reason or "That application needs you. Searching for the next job."
        write_state(
            self.home,
            search_status="running",
            status_line=line,
            current=None,
            submitted=self.totals["submitted"],
            skipped=self.totals["skipped"],
            needs_review=self.totals["needs_review"],
        )

    def _loop(self) -> None:
        configure(self.home)
        write_state(self.home, running=True, search_status="running", status_line="Searching public listings.", current=None)
        try:
            while not self.stop.is_set():
                if self.session.is_open():
                    if self.action.wait(0.8):
                        choice, answers = self._take_choice()
                        if self.stop.is_set() and choice not in {"submit", "skip", "edit"}:
                            break
                        self._resolve(choice, answers)
                        continue
                    try:
                        run_cycle(self.home, self.stop, self.session, self.queue, self.cursor, self.totals)
                    except Exception as exc:
                        logger.error("search error: %s", safe_error(exc))
                    continue
                try:
                    run_cycle(self.home, self.stop, self.session, self.queue, self.cursor, self.totals)
                except Exception as exc:
                    logger.error("cycle error: %s", safe_error(exc))
                    write_state(self.home, running=True, search_status="running", status_line="The last search hit an error. Searching again.")
                if self.stop.is_set():
                    break
                if not self.session.is_open() and not self.queue:
                    self.wake.wait(1.5)
                    self.wake.clear()
        finally:
            self.session.close()
            write_state(self.home, running=False, search_status="stopped", status_line="Stopped.", current=None)
