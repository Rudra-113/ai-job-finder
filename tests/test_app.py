import io
import json
import re
from pathlib import Path

from app import bind_host, create_app
from jobagent.profile import save_profile
from jobagent.runner import run_cycle
from jobagent.settings import save_settings
from tests.conftest import strong_job, strong_profile, strong_settings


def test_browser_missing_page_is_html(tmp_path):
    _app, client = _client(tmp_path)
    moved = client.get("/dashboard", headers={"Accept": "text/html"})
    assert moved.status_code == 302
    assert moved.headers["Location"].endswith("/dashboard.html")
    missing = client.get("/no-such-page", headers={"Accept": "text/html"})
    assert missing.status_code == 404
    assert b"That page was not found." in missing.data
    api_missing = client.get("/no-such-page", headers={"Accept": "application/json"})
    assert api_missing.status_code == 404
    assert api_missing.is_json


def test_bind_host_defaults_to_all_interfaces():
    assert bind_host() == "0.0.0.0"


def _client(tmp_path):
    application = create_app(tmp_path)
    return application, application.test_client()


def _csrf(client) -> str:
    payload = client.get("/api/session").get_json()
    assert payload["csrf"]
    return payload["csrf"]


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "local"
        sess["user_name"] = "Ada Lovelace"


def test_pages_and_csrf_and_host(tmp_path):
    _app, client = _client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json()["status"] == "ok"
    landing = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Find the right job" in landing
    assert "Get Started Free" in landing
    auth = (Path(__file__).resolve().parents[1] / "frontend" / "auth.html").read_text(encoding="utf-8")
    assert "Continue with Google" not in auth
    assert "onboarding.html" in auth
    opened = client.get("/auth")
    assert opened.status_code == 302
    assert opened.headers["Location"].endswith("/onboarding.html")
    assert client.get("/auth/google").status_code == 404
    denied = client.post("/api/search")
    assert denied.status_code == 400
    blocked = client.get("/api/health", base_url="http://evil.example")
    assert blocked.status_code == 403
    _login(client)
    save_profile(tmp_path, strong_profile(tmp_path))
    save_settings(tmp_path, strong_settings())
    home = client.get("/api/home")
    assert home.status_code == 200
    assert "opportunities" in home.get_json()["search"]
    token = _csrf(client)
    missing = client.post("/application/submit", data={"csrf": token})
    assert missing.status_code == 404
    assert client.post("/opportunities/apply", data={"csrf": token}).status_code == 404


def test_settings_roundtrip_and_start_requires_profile(tmp_path):
    app, client = _client(tmp_path)
    _login(client)
    settings_page = client.get("/api/settings").get_json()
    assert "opportunity_count" in settings_page
    assert "avoid_video" in settings_page
    assert "require_disclosed_pay" in settings_page
    token = _csrf(client)
    saved = client.post(
        "/api/settings",
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
    )
    assert saved.status_code == 200
    assert saved.get_json()["message"] == "Settings saved."
    assert "healthcare" in saved.get_json()["settings"]["sector"]
    started = client.post(
        "/api/search",
        data={
            "csrf": token,
            "sector": "data",
            "roles": "data analyst intern",
            "minimum_stipend": "0",
            "minimum_score": "70",
        },
    )
    assert started.status_code == 400
    assert "Profile" in started.get_json()["error"]
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


def test_anonymous_visitors_keep_separate_resumes(tmp_path):
    application = create_app(tmp_path)
    first = application.test_client()
    second = application.test_client()
    session_info = first.get("/api/session").get_json()
    assert session_info["logged_in"] is True
    assert "google_ready" not in session_info
    token = session_info["csrf"]
    uploaded = first.post(
        "/api/onboarding/resume",
        data={"csrf": token, "cv": (io.BytesIO(b"Ada Lovelace\nPython\n"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    assert uploaded.get_json()["profile"]["has_resume"] is True
    assert second.get("/api/profile").get_json()["has_resume"] is False
    with first.session_transaction() as sess:
        visitor = sess["user_id"]
    assert visitor.startswith("anon_")
    assert (tmp_path / "users" / visitor / "profile.json").is_file()
    assert not (tmp_path / "profile.json").exists()
    gone = first.post(
        "/api/auth/google/finish",
        data={"csrf": token, "returned": "http://127.0.0.1/auth/google/callback?code=1&state=abc"},
    )
    assert gone.status_code == 404


def test_cors_allows_only_the_configured_frontend(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://finder.example, https://preview.example")
    _app, client = _client(tmp_path)
    allowed = client.get("/api/health", headers={"Origin": "https://finder.example"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://finder.example"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"
    assert "*" not in allowed.headers.get("Access-Control-Allow-Origin", "")
    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in blocked.headers
    preflight = client.options(
        "/api/search",
        headers={"Origin": "https://preview.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 204
    assert preflight.headers["Access-Control-Allow-Origin"] == "https://preview.example"


def test_resume_upload_rejects_the_wrong_file(tmp_path):
    _app, client = _client(tmp_path)
    _login(client)
    token = _csrf(client)
    rejected = client.post(
        "/api/profile/resume",
        data={"csrf": token, "cv": (io.BytesIO(b"not really a pdf"), "resume.pdf")},
        content_type="multipart/form-data",
    )
    assert rejected.status_code == 400
    assert "PDF" in rejected.get_json()["error"]
    marker = "UniqueResumePhrase"
    accepted = client.post(
        "/api/profile/resume",
        data={"csrf": token, "cv": (io.BytesIO(f"Ada Lovelace\n{marker}\n".encode()), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert accepted.status_code == 200
    profile = client.get("/api/profile").get_json()
    assert profile["cv_name"] == "resume.txt"
    assert profile["has_resume"] is True
    assert "cv_text" not in profile
    assert "cv_path" not in profile
    log_path = tmp_path / "agent.log"
    if log_path.is_file():
        assert marker not in log_path.read_text(encoding="utf-8")


def test_cycle_does_not_search_without_a_profile(tmp_path, monkeypatch):
    def explode(_settings):
        raise AssertionError("search should not run")

    monkeypatch.setattr("jobagent.runner.search_jobs", explode)
    run_cycle(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "Profile" in state["status_line"] or "name" in state["status_line"]
