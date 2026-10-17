import json
import re

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
    token = _csrf(client.get("/settings").data.decode())
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
    monkeypatch.setattr("jobagent.runner.open_application", fake_apply)
    run_cycle(home)
    assert calls == [good.url]
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert state["submitted"] == 1
    assert state["rejected"] >= 2
    calls.clear()
    run_cycle(home)
    assert calls == []


def test_cycle_does_not_search_without_a_profile(tmp_path, monkeypatch):
    def explode(_settings):
        raise AssertionError("search should not run")

    monkeypatch.setattr("jobagent.runner.search_jobs", explode)
    run_cycle(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "Profile" in state["status_line"] or "name" in state["status_line"]
