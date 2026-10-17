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


def _gmail_client(home):
    (home / "gmail_client_secret.json").write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test-client.apps.googleusercontent.com",
                    "client_secret": "test-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )


def test_desktop_gmail_client_starts_google_sign_in(tmp_path):
    from urllib.parse import unquote

    _gmail_client(tmp_path)
    _app, client = _client(tmp_path)
    page = client.get("/auth")
    assert b'href="/auth/google"' in page.data
    started = client.get("/auth/google")
    assert started.status_code == 302
    location = unquote(started.headers["Location"])
    assert location.startswith("https://accounts.google.com/")
    assert "redirect_uri=http://127.0.0.1:47321/auth/google/callback" in location
    assert "gmail.readonly" not in location


def test_matching_gmail_opens_the_saved_profile(tmp_path, monkeypatch):
    _gmail_client(tmp_path)
    save_profile(tmp_path, strong_profile(tmp_path))
    save_settings(tmp_path, strong_settings())
    _app, client = _client(tmp_path)
    monkeypatch.setattr(
        "app.exchange_identity",
        lambda home, redirect_uri, returned: {"sub": "google-sub-1", "email": "Ada@example.com", "name": "Ada Lovelace"},
    )
    assert client.get("/auth/google").status_code == 302
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    done = client.get(f"/auth/google/callback?code=fake-code&state={state}")
    assert done.status_code == 302
    assert done.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess["user_id"] == "local"
    assert not (tmp_path / "users").exists()
    assert client.get("/dashboard").status_code == 200


def test_other_gmail_does_not_open_the_saved_profile(tmp_path, monkeypatch):
    _gmail_client(tmp_path)
    save_profile(tmp_path, strong_profile(tmp_path))
    _app, client = _client(tmp_path)
    monkeypatch.setattr(
        "app.exchange_identity",
        lambda home, redirect_uri, returned: {"sub": "other-person", "email": "other@example.com", "name": "Other Person"},
    )
    client.get("/auth/google")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    done = client.get(f"/auth/google/callback?code=fake-code&state={state}")
    assert done.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == "other-person"
    assert (tmp_path / "users" / "other-person").is_dir()
    saved = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert saved["email"] == "ada@example.com"


def test_public_sign_in_can_finish_from_the_loopback_address(tmp_path, monkeypatch):
    _gmail_client(tmp_path)
    save_profile(tmp_path, strong_profile(tmp_path))
    _app, client = _client(tmp_path)
    monkeypatch.setattr(
        "app.exchange_identity",
        lambda home, redirect_uri, returned: {"sub": "google-sub-1", "email": "ada@example.com", "name": "Ada Lovelace"},
    )
    headers = {"X-Forwarded-Host": "example.trycloudflare.com", "X-Forwarded-Proto": "https"}
    page = client.get("/auth", headers=headers)
    assert b"Google return address" in page.data
    assert client.get("/auth/google", headers=headers).status_code == 302
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
        redirect_uri = sess["oauth_redirect"]
    assert redirect_uri.startswith("http://127.0.0.1:")
    done = client.post(
        "/auth/google/finish",
        data={"csrf": _csrf(page.data.decode()), "returned": f"{redirect_uri}?code=fake-code&state={state}"},
        headers=headers,
    )
    assert done.status_code == 302
    assert done.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess["user_id"] == "local"


def test_paste_rejects_a_public_address(tmp_path):
    _gmail_client(tmp_path)
    _app, client = _client(tmp_path)
    page = client.get("/auth")
    done = client.post(
        "/auth/google/finish",
        data={"csrf": _csrf(page.data.decode()), "returned": "https://evil.example/auth/google/callback?code=1&state=abc"},
    )
    assert done.status_code == 302
    assert done.headers["Location"].endswith("/auth")


def test_cycle_does_not_search_without_a_profile(tmp_path, monkeypatch):
    def explode(_settings):
        raise AssertionError("search should not run")

    monkeypatch.setattr("jobagent.runner.search_jobs", explode)
    run_cycle(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "Profile" in state["status_line"] or "name" in state["status_line"]
