import json
import re

import pytest

from app import bind_host, create_app
from jobagent.models import ApplyResult
from jobagent.profile import save_profile
from jobagent.runner import run_cycle
from jobagent.settings import save_settings
from tests.conftest import strong_job, strong_profile, strong_settings


def test_bind_host_is_loopback():
    assert bind_host() == "127.0.0.1"


def _client(tmp_path):
    application = create_app(tmp_path)
    return application, application.test_client()


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_pages_and_csrf_and_host(tmp_path):
    _app, client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert b"Target sector" in page.data
    assert b"Target roles" in page.data
    assert b"Minimum stipend" in page.data
    assert b"Minimum match score" in page.data
    assert b"Start continuous search" in page.data
    assert b"Nothing is submitted until you click Apply directly." in page.data
    assert b"Number of opportunities" in page.data
    assert b"Found" in page.data
    assert b"Qualified" in page.data
    assert b"Submit" in page.data
    denied = client.post(
        "/start",
        data={"sector": "data", "roles": "analyst", "minimum_stipend": "0", "minimum_score": "70"},
    )
    assert denied.status_code == 400
    blocked = client.get("/", base_url="http://evil.example")
    assert blocked.status_code == 403


def test_settings_roundtrip_and_start_requires_profile(tmp_path):
    app, client = _client(tmp_path)
    settings_page = client.get("/settings").data
    assert b"Number of opportunities" in settings_page
    assert b"Skip mandatory video applications" in settings_page
    assert b"Require disclosed compensation" in settings_page
    token = _csrf(settings_page.decode())
    saved = client.post(
        "/settings",
        data={
            "csrf": token,
            "sector": "data, healthcare",
            "roles": "data analyst intern",
            "required_skills": "Python",
            "location": "Berlin",
            "workplace": "remote",
            "minimum_stipend": "1500",
            "preferred_companies": "Northwind",
            "excluded_companies": "Acme",
            "minimum_score": "75",
        },
        follow_redirects=True,
    )
    assert b"Settings saved." in saved.data
    assert b"data, healthcare" in saved.data
    token = _csrf(client.get("/").data.decode())
    started = client.post(
        "/start",
        data={
            "csrf": token,
            "sector": "data",
            "roles": "data analyst intern",
            "minimum_stipend": "0",
            "minimum_score": "70",
        },
        follow_redirects=True,
    )
    assert b"Profile" in started.data
    assert app.extensions["agent"].running() is False
    state_file = tmp_path / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["running"] is False


def test_cycle_applies_once_and_skips_the_rest(tmp_path, monkeypatch):
    home = tmp_path
    save_profile(home, strong_profile(home))
    save_settings(home, strong_settings())
    good = strong_job()
    unpaid = strong_job(
        company="Other",
        title="Data Analyst Intern",
        url="https://jobs.example.com/unpaid",
        apply_url="https://jobs.example.com/unpaid",
        description="This is an unpaid data internship using Python.",
        salary_min=None,
        salary_period="",
        salary_text="",
    )
    outside = strong_job(
        company="Brand",
        title="Marketing Manager",
        url="https://jobs.example.com/marketing",
        apply_url="https://jobs.example.com/marketing",
        category="Marketing",
        description="Brand campaigns and social media.",
        tags=[],
    )
    calls = []

    def fake_apply(job, *_args, **_kwargs):
        calls.append(job.url)
        return ApplyResult("submitted", "The site confirmed the application.", "", True, True)

    monkeypatch.setattr("jobagent.runner.search_jobs", lambda _settings, _queries=None: ([good, unpaid, outside], []))
    monkeypatch.setattr("jobagent.runner.polite_fetcher", lambda _url: None)
    monkeypatch.setattr("jobagent.runner.open_application", fake_apply)
    run_cycle(home)
    assert calls == []
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert state["submitted"] == 0
    assert state["final_count"] == 1
    assert state["opportunities"][0]["company"] == "Northwind"
    assert state["rejected"] >= 2


def test_search_lists_jobs_and_selected_applies_run(tmp_path, monkeypatch):
    home = tmp_path
    save_profile(home, strong_profile(home))
    save_settings(home, strong_settings())
    jobs = [
        strong_job(company=f"Co{index}", url=f"https://jobs.example.com/c{index}", apply_url=f"https://jobs.example.com/c{index}")
        for index in range(5)
    ]
    seen = []

    def fake_apply(job, *_args, **_kwargs):
        seen.append(job.company)
        if job.company == "Co1":
            return ApplyResult("needs_user", "", "A CAPTCHA or human check appeared. This application was not submitted.", True, False)
        if job.company == "Co2":
            return ApplyResult("failed", "", "Could not find an application form on this page.", True, False)
        return ApplyResult("submitted", "The site confirmed the application.", "", True, True)

    monkeypatch.setattr("jobagent.runner.search_jobs", lambda _settings, _queries=None: (jobs, []))
    monkeypatch.setattr("jobagent.runner.polite_fetcher", lambda _url: None)
    monkeypatch.setattr("jobagent.runner.open_application", fake_apply)
    run_cycle(home)
    assert seen == []
    listed = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert listed["submitted"] == 0
    assert listed["final_count"] == 5
    assert {card["company"] for card in listed["opportunities"]} == {f"Co{index}" for index in range(5)}

    queue = [(job, 90) for job in jobs]
    totals = {
        "found": listed["found"],
        "rejected": listed["rejected"],
        "qualified": listed["qualified"],
        "needs_review": 0,
        "filled": 0,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
    }
    for _ in range(5):
        run_cycle(home, queue=queue, totals=totals)
    assert seen == ["Co0", "Co1", "Co2", "Co3", "Co4"]
    assert queue == []
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert state["submitted"] == 3
    assert state["needs_review"] == 1
    assert state["failed"] == 1
    records = json.loads((home / "applications.json").read_text(encoding="utf-8"))
    submitted = next(row for row in records if row["company"] == "Co0")
    assert submitted["status"] == "submitted"
    assert submitted["submitted_at"]
    assert submitted["found_at"]
    assert submitted["resume"] == "cv.txt"
    assert submitted["match_score"] >= 70
    assert submitted["application_url"].startswith("https://jobs.example.com/c0")


def test_runner_submits_a_local_form_then_records_the_captcha(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("JOBAGENT_HEADLESS", "1")
    from tests.test_apply import CAPTCHA, FORM, serve

    home = tmp_path
    save_profile(home, strong_profile(home))
    save_settings(home, strong_settings())
    ready = serve(FORM)
    blocked = serve(CAPTCHA)
    good_url = f"http://127.0.0.1:{ready.server_address[1]}/job"
    bad_url = f"http://127.0.0.1:{blocked.server_address[1]}/job"
    good = strong_job(company="Northwind", url=good_url, apply_url=good_url)
    bad = strong_job(company="Blocked", url=bad_url, apply_url=bad_url)
    queue = [(good, 90), (bad, 90)]
    totals = {
        "found": 0,
        "rejected": 0,
        "qualified": 2,
        "needs_review": 0,
        "filled": 0,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
    }
    try:
        run_cycle(home, queue=queue, totals=totals)
        run_cycle(home, queue=queue, totals=totals)
    finally:
        ready.shutdown()
        ready.server_close()
        blocked.shutdown()
        blocked.server_close()
    assert ready.posts
    assert blocked.posts == []
    records = json.loads((home / "applications.json").read_text(encoding="utf-8"))
    by_company = {row["company"]: row for row in records}
    assert by_company["Northwind"]["status"] == "submitted"
    assert by_company["Northwind"]["submitted_at"]
    assert by_company["Northwind"]["resume"] == "cv.txt"
    assert by_company["Northwind"]["match_score"] >= 70
    assert by_company["Blocked"]["status"] == "needs_user"
    assert "captcha" in by_company["Blocked"]["reason"].lower()
    assert queue == []


def test_apply_directly_uses_only_the_clicked_job(tmp_path, monkeypatch):
    app, client = _client(tmp_path)
    from jobagent.runner import write_state

    write_state(
        tmp_path,
        opportunities=[
            {
                "id": "aaa",
                "company": "Northwind",
                "role": "Data Analyst Intern",
                "url": "https://jobs.example.com/a",
                "source_url": "https://www.linkedin.com/jobs/view/a",
                "match_score": 90,
            },
            {
                "id": "bbb",
                "company": "Other",
                "role": "Data Analyst Intern",
                "url": "https://jobs.example.com/b",
                "source_url": "https://jobs.example.com/b",
                "match_score": 80,
            },
        ],
    )
    captured = []
    monkeypatch.setattr(app.extensions["agent"], "request_apply", lambda items: captured.append(items))
    token = _csrf(client.get("/").data.decode())
    empty = client.post("/opportunities/apply", data={"csrf": token}, follow_redirects=True)
    assert b"Select an opportunity before applying." in empty.data
    assert captured == []
    chosen = client.post(
        "/opportunities/apply",
        data={"csrf": token, "apply_one": "aaa", "job_id": ["aaa", "bbb"]},
        follow_redirects=True,
    )
    assert b"Applying to 1 selected job." in chosen.data
    assert len(captured) == 1
    assert len(captured[0]) == 1
    assert captured[0][0][0].company == "Northwind"
    assert captured[0][0][0].apply_url == "https://jobs.example.com/a"


def test_cycle_does_not_search_without_a_profile(tmp_path, monkeypatch):
    def explode(_settings):
        raise AssertionError("search should not run")

    monkeypatch.setattr("jobagent.runner.search_jobs", explode)
    run_cycle(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "Profile" in state["status_line"] or "name" in state["status_line"]
