"""Search listings and rank them. This process does not submit applications."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from jobagent.history import save_search
from jobagent.intelligence import analyze_job_market, polite_fetcher
from jobagent.logsetup import configure, safe_error
from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.profile import load_profile
from jobagent.search import search_all_sources
from jobagent.settings import load_settings

logger = logging.getLogger("jobagent")


def state_path(home: Path) -> Path:
    return home / "state.json"


def default_state() -> dict:
    return {
        "running": False,
        "search_status": "stopped",
        "found": 0,
        "discovered": 0,
        "rejected": 0,
        "qualified": 0,
        "strong_matches": 0,
        "needs_review": 0,
        "filled": 0,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
        "status_line": "Tell us what you are looking for.",
        "phase": "",
        "query": "",
        "opportunities": [],
        "source_report": [],
        "analyzed": 0,
        "active": 0,
        "duplicates": 0,
        "final_count": 0,
        "relaxed": False,
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


def search_jobs(settings, queries=None):
    return search_all_sources(settings, queries)


def run_cycle(home: Path, stop: threading.Event | None = None, query: str = "") -> None:
    configure(home)
    stop = stop or threading.Event()
    profile = load_profile(home)
    problem = profile.problem()
    if problem:
        write_state(home, status_line=problem, search_status="stopped", running=False, phase="")
        return
    settings = load_settings(home)
    if not settings.sectors or not settings.roles:
        write_state(home, status_line="Add a target sector and at least one role before searching.", running=False)
        return

    def progress(message: str) -> None:
        if stop.is_set():
            return
        write_state(home, running=True, search_status="running", status_line=message, phase=message, query=query)

    progress("Searching job sources...")
    try:
        report = analyze_job_market(profile, settings, search=search_jobs, fetcher=polite_fetcher, progress=progress)
    except Exception as exc:
        logger.error("search error: %s", safe_error(exc))
        write_state(home, running=False, search_status="stopped", status_line="Search failed before any listing was analyzed.", phase="", warnings=["Search"])
        return
    if stop.is_set():
        write_state(home, running=False, search_status="stopped", status_line="Stopped.", phase="", warnings=report.get("warnings") or [])
        return
    count = report["final_count"]
    if report.get("relaxed") and count:
        line = f"{count} closest opportunities, each with a direct application link. None cleared every filter."
    elif count:
        line = f"{count} best opportunities found."
    else:
        line = "No matching opportunities in this search."
    try:
        save_search(home, query or ", ".join(settings.roles), report)
    except OSError:
        logger.error("could not save search history")
    write_state(
        home,
        running=False,
        search_status="ready",
        status_line=line,
        phase="",
        query=query,
        opportunities=report["opportunities"],
        source_report=report["source_report"],
        analyzed=report["analyzed"],
        active=report["active"],
        duplicates=report["duplicates"],
        final_count=count,
        relaxed=bool(report.get("relaxed")),
        found=report["found"],
        discovered=report.get("discovered") or report["found"],
        rejected=report["rejected"],
        qualified=report["qualified"],
        strong_matches=report["qualified"],
        warnings=report["warnings"],
        rejection_counts=report["rejection_counts"],
        queue_size=0,
        current=None,
    )


class AgentService:
    def __init__(self, home: Path):
        self.home = home
        self.stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.query = ""

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, home: Path | None = None, query: str = "") -> None:
        with self._lock:
            if self.running():
                return
            if home is not None:
                self.home = home
            self.query = query
            self.stop.clear()
            self._thread = threading.Thread(target=self._loop, name="job-search", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        self.stop.set()

    def _loop(self) -> None:
        configure(self.home)
        write_state(self.home, running=True, search_status="running", status_line="Searching job sources...", phase="Searching job sources...")
        try:
            run_cycle(self.home, self.stop, self.query)
        except Exception as exc:
            logger.error("cycle error: %s", safe_error(exc))
            write_state(self.home, running=False, search_status="stopped", status_line="The last search hit an error.", phase="")
        finally:
            if self.stop.is_set() and load_state(self.home).get("search_status") == "running":
                write_state(self.home, running=False, search_status="stopped", status_line="Stopped.", phase="")
