import json
import re

import pytest

from app import bind_host, create_app
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


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "local"
        sess["user_name"] = "Ada Lovelace"


def test_pages_and_csrf_and_host(tmp_path):
    _app, client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert b"Find the right job" in page.data
    assert b"Get Started Free" in page.data
    assert b"Continue with Google" in client.get("/auth").data
    assert b"Apply directly" not in page.data
    denied = client.post("/auth/local")
    assert denied.status_code == 400
    blocked = client.get("/", base_url="http://evil.example")
    assert blocked.status_code == 403
    _login(client)
    save_profile(tmp_path, strong_profile(tmp_path))
    save_settings(tmp_path, strong_settings())
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b"What are you looking for?" in dashboard.data
    assert b"Number of opportunities" in dashboard.data
    assert b"Apply directly" not in dashboard.data
    assert b"Apply on official site" not in dashboard.data or b"best opportunities" in dashboard.data
    token = _csrf(dashboard.data.decode())
    missing = client.post("/application/submit", data={"csrf": token})
    assert missing.status_code == 404
    assert client.post("/opportunities/apply", data={"csrf": token}).status_code == 404


def test_settings_roundtrip_and_start_requires_profile(tmp_path):
    app, client = _client(tmp_path)
    _login(client)
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
    token = _csrf(client.get("/onboarding").data.decode())
    started = client.post(
        "/search",
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
    monkeypatch.setattr("jobagent.runner.search_jobs", lambda _settings, _queries=None: ([good, unpaid, outside], []))
    monkeypatch.setattr("jobagent.runner.polite_fetcher", lambda _url: None)
    run_cycle(home)
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert state["submitted"] == 0
    assert state["final_count"] == 1
    assert state["opportunities"][0]["company"] == "Northwind"
    assert state["rejected"] >= 2


def test_search_lists_jobs_without_applying(tmp_path, monkeypatch):
    home = tmp_path
    save_profile(home, strong_profile(home))
    save_settings(home, strong_settings())
    jobs = [
        strong_job(company=f"Co{index}", url=f"https://jobs.example.com/c{index}", apply_url=f"https://jobs.example.com/c{index}")
        for index in range(5)
    ]
    monkeypatch.setattr("jobagent.runner.search_jobs", lambda _settings, _queries=None: (jobs, []))
    monkeypatch.setattr("jobagent.runner.polite_fetcher", lambda _url: None)
    run_cycle(home)
    listed = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert listed["submitted"] == 0
    assert listed["final_count"] == 5
    assert {card["company"] for card in listed["opportunities"]} == {f"Co{index}" for index in range(5)}
    assert not (home / "applications.json").exists()


def test_cycle_does_not_search_without_a_profile(tmp_path, monkeypatch):
    def explode(_settings):
        raise AssertionError("search should not run")

    monkeypatch.setattr("jobagent.runner.search_jobs", explode)
    run_cycle(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "Profile" in state["status_line"] or "name" in state["status_line"]
