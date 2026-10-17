"""Local page for the job agent. It listens on 127.0.0.1 only."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

from jobagent.gmail_otp import (
    GmailNotConnected,
    connect_gmail,
    credentials_path,
    disconnect_gmail,
    gmail_connected,
    valid_client_file,
)
from jobagent.logsetup import configure
from jobagent.paths import default_home, load_secret_key
from jobagent.profile import extract_cv_text, load_profile, save_profile, validate_profile_fields
from jobagent.runner import AgentService, load_state, write_state
from jobagent.secrets import api_key_is_set, load_secrets, update_secrets_from_form
from jobagent.settings import apply_main_fields, apply_settings_form, load_settings, save_settings
from jobagent.store import Store
from jobagent.textutil import safe_http_url

ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CV_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def bind_host() -> str:
    return "127.0.0.1"


def create_app(home: Path | None = None) -> Flask:
    home = Path(home) if home is not None else default_home()
    home.mkdir(parents=True, exist_ok=True)
    configure(home)
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["SECRET_KEY"] = load_secret_key(home / "secret.key")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.extensions["home"] = home
    Store(home).recover()
    if load_state(home).get("running") or load_state(home).get("search_status") in {"running", "paused"}:
        write_state(
            home,
            running=False,
            search_status="stopped",
            status_line="Stopped because the app was restarted.",
            current=None,
        )
    app.extensions["agent"] = AgentService(home)

    def current_home() -> Path:
        return app.extensions["home"]

    def agent() -> AgentService:
        return app.extensions["agent"]

    def set_flash(message: str) -> None:
        session["flash"] = message

    def pop_flash() -> str:
        return session.pop("flash", "")

    @app.before_request
    def guard():
        host = request.host.split(":")[0]
        if host not in ALLOWED_HOSTS:
            abort(403)
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST":
            token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
            if not token or token != session.get("csrf"):
                abort(400)

    @app.context_processor
    def inject() -> dict:
        return {"csrf": session.get("csrf", ""), "active": ""}

    @app.get("/")
    def index():
        home_path = current_home()
        settings = load_settings(home_path)
        snap = _snapshot(home_path)
        return render_template(
            "index.html",
            title="Search",
            active="search",
            settings=settings,
            sector=", ".join(settings.sectors),
            roles=", ".join(settings.roles),
            flash=pop_flash(),
            **snap,
        )

    @app.post("/start")
    def start():
        home_path = current_home()
        settings = load_settings(home_path)
        error = apply_main_fields(settings, request.form)
        if error:
            set_flash(error)
            return redirect(url_for("index"))
        save_settings(home_path, settings)
        problem = load_profile(home_path).problem()
        if problem:
            set_flash(problem)
            return redirect(url_for("index"))
        if agent().running():
            set_flash("A search is already running.")
            return redirect(url_for("index"))
        agent().start()
        return redirect(url_for("index"))

    @app.post("/stop")
    def stop():
        agent().request_stop()
        set_flash("Stopping. An open form is closed without submitting.")
        return redirect(url_for("index"))

    @app.post("/application/submit")
    def submit_application():
        agent().request_submit()
        set_flash("Submitting the open application.")
        return redirect(url_for("index"))

    @app.post("/application/skip")
    def skip_application():
        agent().request_skip()
        set_flash("Skipped. Nothing was submitted.")
        return redirect(url_for("index"))

    @app.post("/application/edit")
    def edit_application():
        answers = {}
        for line in (request.form.get("notes") or "").splitlines():
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            if label.strip() and value.strip():
                answers[label.strip()] = value.strip()
        if not answers:
            set_flash("Add one true answer per line, written as Question: answer.")
        else:
            agent().request_edit(answers)
            set_flash("Adding those answers on the open form. Nothing was submitted.")
        return redirect(url_for("index"))

    @app.get("/settings")
    def settings_page():
        settings = load_settings(current_home())
        return render_template(
            "settings.html",
            title="Settings",
            active="settings",
            settings=settings,
            sector=", ".join(settings.sectors),
            roles=", ".join(settings.roles),
            required_skills=", ".join(settings.required_skills),
            preferred=", ".join(settings.preferred_companies),
            excluded=", ".join(settings.excluded_companies),
            flash=pop_flash(),
        )

    @app.post("/settings")
    def save_settings_page():
        settings, error = apply_settings_form(request.form)
        if error:
            set_flash(error)
            return redirect(url_for("settings_page"))
        save_settings(current_home(), settings)
        set_flash("Settings saved.")
        return redirect(url_for("settings_page"))

    @app.get("/profile")
    def profile_page():
        home_path = current_home()
        profile = load_profile(home_path)
        secrets = load_secrets(home_path)
        return render_template(
            "profile.html",
            title="Profile",
            active="profile",
            profile=profile,
            cv_name=Path(profile.cv_path).name if profile.cv_path else "",
            gmail_connected=gmail_connected(home_path),
            gmail_file=credentials_path(home_path).exists(),
            api_base=secrets.api_base,
            api_model=secrets.api_model,
            api_key_set=api_key_is_set(home_path),
            flash=pop_flash(),
        )

    @app.post("/profile")
    def save_profile_page():
        home_path = current_home()
        payload, error, warnings = validate_profile_fields(request.form)
        if error:
            set_flash(error)
            return redirect(url_for("profile_page"))
        secret_error = update_secrets_from_form(home_path, request.form)
        if secret_error:
            set_flash(secret_error)
            return redirect(url_for("profile_page"))
        upload_error = _save_gmail_client(home_path)
        if upload_error:
            set_flash(upload_error)
            return redirect(url_for("profile_page"))
        profile = load_profile(home_path)
        for key, value in payload.items():
            setattr(profile, key, value)
        cv_note = _save_cv(home_path, profile)
        save_profile(home_path, profile)
        note = "Profile saved."
        if cv_note:
            note += " " + cv_note
        if warnings:
            note += " Some education or experience lines do not use the | format, so their dates will not be calculated."
        set_flash(note)
        return redirect(url_for("profile_page"))

    @app.post("/gmail/connect")
    def gmail_connect():
        try:
            connect_gmail(current_home())
        except GmailNotConnected as exc:
            set_flash(str(exc))
            return redirect(url_for("profile_page"))
        except Exception:
            set_flash("Gmail was not connected. Check the client file and that your account is a test user.")
            return redirect(url_for("profile_page"))
        set_flash("Gmail connected. Only a matching one-time-code email is read.")
        return redirect(url_for("profile_page"))

    @app.post("/gmail/disconnect")
    def gmail_disconnect():
        disconnect_gmail(current_home())
        set_flash("Gmail disconnected. The saved token was deleted.")
        return redirect(url_for("profile_page"))

    @app.post("/attention/<record_id>/retry")
    def retry(record_id: str):
        if Store(current_home()).clear_block(record_id):
            if agent().running():
                agent().request_cycle()
                set_flash("Queued for the next pass. Captcha, payment, and login checks still apply.")
            else:
                set_flash("Saved. Start search when you want to try again. Safety checks still apply.")
        return redirect(url_for("index"))

    @app.post("/attention/<record_id>/dismiss")
    def dismiss(record_id: str):
        if Store(current_home()).dismiss(record_id):
            set_flash("That job will not be applied to.")
        return redirect(url_for("index"))

    @app.get("/api/status")
    def status():
        return jsonify(_snapshot(current_home()))

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", title="Form expired", message="Reload the page and submit the form again."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", title="Local only", message="This app only answers on this computer."), 403

    @app.errorhandler(404)
    def missing(_error):
        return render_template("error.html", title="Not found", message="That page does not exist."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", title="File too large", message="The upload is larger than 8 MB."), 413

    return app


def _snapshot(home: Path) -> dict:
    state = load_state(home)
    state["running"] = state.get("running") and True
    records = Store(home).records()
    submitted = [row for row in records if row.get("status") == "submitted"]
    submitted.sort(key=lambda row: (row.get("date") or "", row.get("company") or ""), reverse=True)
    attention = [row for row in records if row.get("status") == "needs_user"]
    for row in submitted + attention:
        row["url"] = safe_http_url(row.get("url") or "")
    current = state.get("current") if isinstance(state.get("current"), dict) else None
    if current:
        current["url"] = safe_http_url(current.get("url") or "")
    return {
        "running": bool(state.get("running")),
        "search_status": state.get("search_status") or ("running" if state.get("running") else "stopped"),
        "found": state.get("found") or 0,
        "rejected": state.get("rejected") or 0,
        "qualified": state.get("qualified") or 0,
        "needs_review": state.get("needs_review") or 0,
        "filled": state.get("filled") or 0,
        "submitted": state.get("submitted") or 0,
        "skipped": state.get("skipped") or 0,
        "failed": state.get("failed") or 0,
        "queue_size": state.get("queue_size") or 0,
        "status_line": state.get("status_line") or "",
        "warnings": state.get("warnings") or [],
        "failures": state.get("failures") or [],
        "rejection_counts": state.get("rejection_counts") or {},
        "current": current,
        "applications": submitted[:100],
        "attention": attention,
    }


def _save_cv(home: Path, profile) -> str:
    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return ""
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in CV_EXTENSIONS:
        return "The CV was not replaced. Use a PDF, DOCX, TXT, or MD file."
    blob = upload.read()
    if len(blob) > 5 * 1024 * 1024:
        return "The CV was not replaced. It must be 5 MB or smaller."
    dest = home / "cv" / f"cv{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    profile.cv_path = str(dest)
    profile.cv_text = extract_cv_text(dest)
    if not profile.cv_text.strip():
        return "The file was saved, but no text could be read. A scanned PDF will not score well."
    return ""


def _save_gmail_client(home: Path) -> str | None:
    upload = request.files.get("gmail_client")
    if upload is None or not upload.filename:
        return None
    blob = upload.read(1_000_000)
    if len(blob) > 500_000:
        return "The OAuth file is too large."
    dest = credentials_path(home)
    dest.write_bytes(blob)
    if not valid_client_file(dest):
        dest.unlink(missing_ok=True)
        return "That file is not a Google OAuth client JSON."
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return None


def load_env_file() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    load_env_file()
    host = bind_host()
    port = int(os.environ.get("JOBAGENT_PORT", "47321"))
    if not 1 <= port <= 65535:
        raise SystemExit("JOBAGENT_PORT must be between 1 and 65535.")
    application = create_app(default_home())
    print(f"Job Agent is running only on this computer: http://{host}:{port}", flush=True)
    application.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
