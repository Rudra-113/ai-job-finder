"""AI Job & Internship Finder. Search and ranking only. It does not submit applications."""

from __future__ import annotations

import os
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

from jobagent.accounts import user_home, workspace_id
from jobagent.auth_google import authorization_url, exchange_identity, google_ready, loopback_return, sign_in_redirect
from jobagent.history import find_search, load_history
from jobagent.logsetup import configure
from jobagent.paths import default_home, load_secret_key
from jobagent.profile import extract_cv_text, load_profile, save_profile, validate_profile_fields
from jobagent.resume_extract import apply_extraction, extract_resume
from jobagent.runner import AgentService, load_state, write_state
from jobagent.settings import apply_main_fields, apply_settings_form, load_settings, save_settings
from jobagent.textutil import safe_http_url

ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CV_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
PUBLIC_PATHS = {
    "/",
    "/auth",
    "/auth/google",
    "/auth/google/callback",
    "/auth/google/finish",
    "/auth/google/complete",
    "/auth/local",
    "/privacy",
    "/terms",
}


def bind_host() -> str:
    return "127.0.0.1"


def create_app(home: Path | None = None) -> Flask:
    home = Path(home) if home is not None else default_home()
    home.mkdir(parents=True, exist_ok=True)
    configure(home)
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.config["SECRET_KEY"] = load_secret_key(home / "secret.key")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.extensions["home"] = home
    app.extensions["agent"] = AgentService(home)

    def root_home() -> Path:
        return app.extensions["home"]

    def signed_in() -> bool:
        return bool(session.get("user_id"))

    def current_home() -> Path:
        return user_home(root_home(), session.get("user_id") or "")

    def agent() -> AgentService:
        return app.extensions["agent"]

    def set_flash(message: str) -> None:
        session["flash"] = message

    def pop_flash() -> str:
        return session.pop("flash", "")

    def base_url() -> str:
        forwarded = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        proto = (request.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip() or "http"
        host = forwarded.split(":")[0]
        if host.endswith("trycloudflare.com") or host in ALLOWED_HOSTS:
            return f"{proto}://{forwarded}".rstrip("/")
        return request.host_url.rstrip("/")

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
        if request.path.startswith("/static") or request.path in PUBLIC_PATHS:
            return
        if not signed_in():
            return redirect(url_for("auth_page"))

    @app.context_processor
    def inject() -> dict:
        return {
            "csrf": session.get("csrf", ""),
            "active": "",
            "logged_in": signed_in(),
            "user_name": session.get("user_name") or "",
        }

    @app.get("/")
    def landing():
        if signed_in():
            return redirect(url_for("dashboard"))
        return render_template("landing.html", title="AI Job Finder", active="home")

    def _oauth_box() -> dict:
        return app.extensions.setdefault("oauth_pending", {})

    def _remember_oauth(state: str, redirect_uri: str, return_to: str) -> None:
        now = time.time()
        pending = _oauth_box()
        for key, row in list(pending.items()):
            if now - float(row.get("created") or 0) > 600:
                pending.pop(key, None)
        pending[state] = {"redirect_uri": redirect_uri, "return_to": return_to, "created": now}

    def _pending_oauth(state: str) -> dict | None:
        row = _oauth_box().get(state)
        if not row:
            return None
        if time.time() - float(row.get("created") or 0) > 600:
            _oauth_box().pop(state, None)
            return None
        return row

    def _drop_oauth(state: str) -> None:
        _oauth_box().pop(state, None)

    def _remember_ticket(identity: dict) -> str:
        ticket = secrets.token_urlsafe(24)
        now = time.time()
        tickets = app.extensions.setdefault("oauth_tickets", {})
        for key, row in list(tickets.items()):
            if now - float(row.get("created") or 0) > 120:
                tickets.pop(key, None)
        tickets[ticket] = {"identity": identity, "created": now}
        return ticket

    def _take_ticket(ticket: str) -> dict | None:
        row = app.extensions.setdefault("oauth_tickets", {}).pop(ticket, None)
        if not row or time.time() - float(row.get("created") or 0) > 120:
            return None
        identity = row.get("identity")
        return identity if isinstance(identity, dict) else None

    def _listen_port() -> int:
        host = request.host or ""
        if ":" in host:
            try:
                return int(host.rsplit(":", 1)[1])
            except ValueError:
                pass
        try:
            return int(os.environ.get("JOBAGENT_PORT", "47321"))
        except ValueError:
            return 47321

    def _public_sign_in() -> bool:
        host = urlsplit(base_url()).hostname or ""
        return host.endswith("trycloudflare.com")

    @app.get("/auth")
    def auth_page():
        if signed_in():
            return redirect(url_for("dashboard"))
        ready = google_ready(root_home())
        return render_template(
            "auth.html",
            title="Sign in",
            active="auth",
            google_ready=ready,
            remote_auth=ready and _public_sign_in(),
            flash=pop_flash(),
        )

    @app.get("/auth/google")
    def google_start():
        if not google_ready(root_home()):
            set_flash("Add the Gmail OAuth client file on this computer, then try Google sign-in again.")
            return redirect(url_for("auth_page"))
        redirect_uri = sign_in_redirect(root_home(), base_url(), _listen_port())
        try:
            url, state = authorization_url(root_home(), redirect_uri)
        except Exception:
            set_flash("Google sign-in could not start. Check the OAuth client and redirect URI.")
            return redirect(url_for("auth_page"))
        session["oauth_state"] = state
        session["oauth_redirect"] = redirect_uri
        _remember_oauth(state, redirect_uri, base_url())
        return redirect(url)

    def _identity_from_return(redirect_uri: str, returned: str) -> dict:
        return exchange_identity(root_home(), redirect_uri, returned)

    @app.get("/auth/google/callback")
    def google_callback():
        if request.args.get("error"):
            set_flash("Google sign-in was cancelled.")
            return redirect(url_for("auth_page"))
        state = request.args.get("state") or ""
        expected = session.get("oauth_state") or ""
        pending = _pending_oauth(state)
        if not state or (state != expected and not pending):
            set_flash("The Google sign-in expired. Try again.")
            return redirect(url_for("auth_page"))
        redirect_uri = session.get("oauth_redirect") or (pending or {}).get("redirect_uri") or sign_in_redirect(root_home(), base_url(), _listen_port())
        returned = base_url() + request.full_path
        try:
            identity = _identity_from_return(redirect_uri, returned)
        except Exception:
            set_flash("Google did not complete sign-in. Nothing was stored.")
            return redirect(url_for("auth_page"))
        _drop_oauth(state)
        session.pop("oauth_state", None)
        session.pop("oauth_redirect", None)
        return_to = (pending or {}).get("return_to") or ""
        if state != expected and return_to and return_to != base_url():
            ticket = _remember_ticket(identity)
            return redirect(f"{return_to}/auth/google/complete?ticket={ticket}")
        _start_session(identity["sub"], identity["name"], identity["email"])
        return redirect(url_for("dashboard"))

    @app.post("/auth/google/finish")
    def google_finish():
        returned = (request.form.get("returned") or "").strip()
        if not loopback_return(returned):
            set_flash("Paste the full address from the page Google opened, starting with http://127.0.0.1.")
            return redirect(url_for("auth_page"))
        query = parse_qs(urlsplit(returned).query)
        state = (query.get("state") or [""])[0]
        expected = session.get("oauth_state") or ""
        pending = _pending_oauth(state)
        if not state or (state != expected and not pending):
            set_flash("That Google sign-in has expired. Start it again.")
            return redirect(url_for("auth_page"))
        if query.get("error"):
            set_flash("Google sign-in was cancelled.")
            return redirect(url_for("auth_page"))
        redirect_uri = session.get("oauth_redirect") or (pending or {}).get("redirect_uri") or ""
        try:
            identity = _identity_from_return(redirect_uri, returned)
        except Exception:
            set_flash("Google did not complete sign-in. Nothing was stored.")
            return redirect(url_for("auth_page"))
        _drop_oauth(state)
        session.pop("oauth_state", None)
        session.pop("oauth_redirect", None)
        _start_session(identity["sub"], identity["name"], identity["email"])
        return redirect(url_for("dashboard"))

    @app.get("/auth/google/complete")
    def google_complete():
        identity = _take_ticket(request.args.get("ticket") or "")
        if not identity:
            set_flash("That Google sign-in has expired. Start it again.")
            return redirect(url_for("auth_page"))
        _start_session(str(identity.get("sub") or ""), str(identity.get("name") or ""), str(identity.get("email") or ""))
        return redirect(url_for("dashboard"))

    @app.post("/auth/local")
    def local_sign_in():
        _start_session("local", "Workspace", "")
        return redirect(url_for("dashboard"))

    def _start_session(user_id: str, name: str, email: str) -> None:
        if user_id != "local":
            user_id = workspace_id(root_home(), email, user_id)
        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email
        home_path = user_home(root_home(), user_id)
        profile = load_profile(home_path)
        if email and not profile.email:
            profile.email = email
        if name and " " in name and not profile.full_name:
            profile.full_name = name
        save_profile(home_path, profile)

    @app.post("/logout")
    def logout():
        session.pop("user_id", None)
        session.pop("user_name", None)
        session.pop("user_email", None)
        return redirect(url_for("landing"))

    @app.get("/dashboard")
    def dashboard():
        home_path = current_home()
        profile = load_profile(home_path)
        settings = load_settings(home_path)
        if not profile.onboarded:
            if profile.problem() is None and settings.sectors and settings.roles:
                profile.onboarded = True
                save_profile(home_path, profile)
            else:
                return redirect(url_for("onboarding"))
        settings = load_settings(home_path)
        snap = _snapshot(home_path)
        active_count = snap.pop("active", 0)
        return render_template(
            "dashboard.html",
            title="Search",
            active="search",
            active_count=active_count,
            settings=settings,
            profile=profile,
            history=load_history(home_path)[:8],
            flash=pop_flash(),
            **snap,
        )

    @app.get("/onboarding")
    def onboarding():
        home_path = current_home()
        profile = load_profile(home_path)
        settings = load_settings(home_path)
        return render_template(
            "onboarding.html",
            title="Set up",
            active="profile",
            profile=profile,
            settings=settings,
            extracted=_profile_view(profile),
            flash=pop_flash(),
        )

    @app.post("/onboarding/resume")
    def onboarding_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        note = _save_cv(home_path, profile)
        if profile.cv_text:
            apply_extraction(profile, extract_resume(profile.cv_text), overwrite=False)
        save_profile(home_path, profile)
        set_flash(note or "Resume read. Check the profile before continuing.")
        return redirect(url_for("onboarding"))

    @app.post("/onboarding/confirm")
    def onboarding_confirm():
        home_path = current_home()
        payload, error, _warnings = validate_profile_fields(request.form)
        if error:
            set_flash(error)
            return redirect(url_for("onboarding"))
        profile = load_profile(home_path)
        for key, value in payload.items():
            setattr(profile, key, value)
        profile.onboarded = True
        save_profile(home_path, profile)
        settings = load_settings(home_path)
        _preferences_from_form(settings, request.form)
        save_settings(home_path, settings)
        problem = profile.problem()
        if problem:
            profile.onboarded = False
            save_profile(home_path, profile)
            set_flash(problem)
            return redirect(url_for("onboarding"))
        return redirect(url_for("dashboard"))

    @app.post("/search")
    def start_search():
        home_path = current_home()
        settings = load_settings(home_path)
        error = apply_main_fields(settings, request.form)
        if error:
            set_flash(error)
            return redirect(url_for("dashboard"))
        save_settings(home_path, settings)
        problem = load_profile(home_path).problem()
        if problem:
            set_flash(problem)
            return redirect(url_for("onboarding"))
        if agent().running():
            set_flash("A search is already running.")
            return redirect(url_for("dashboard"))
        agent().start(home_path, (request.form.get("request") or "").strip())
        return redirect(url_for("dashboard"))

    @app.post("/stop")
    def stop():
        agent().request_stop()
        set_flash("Stopping the search. No application is sent.")
        return redirect(url_for("dashboard"))

    @app.post("/history/<search_id>/open")
    def open_history(search_id: str):
        home_path = current_home()
        row = find_search(home_path, search_id)
        if not row:
            set_flash("That search is not on this account.")
            return redirect(url_for("dashboard"))
        write_state(
            home_path,
            running=False,
            search_status="ready",
            status_line=f"{row.get('final_count') or 0} opportunities from a saved search.",
            query=row.get("query") or "",
            opportunities=row.get("opportunities") or [],
            source_report=row.get("source_report") or [],
            found=row.get("discovered") or 0,
            discovered=row.get("discovered") or 0,
            analyzed=row.get("unique") or 0,
            active=row.get("active") or 0,
            qualified=row.get("strong") or 0,
            strong_matches=row.get("strong") or 0,
            final_count=row.get("final_count") or 0,
            phase="",
        )
        return redirect(url_for("dashboard"))

    @app.route("/opportunities/<opportunity_id>", methods=["GET", "POST"])
    def opportunity(opportunity_id: str):
        import re

        if request.method != "GET" or not re.fullmatch(r"[0-9a-f]{8,64}", opportunity_id):
            abort(404)
        cards = load_state(current_home()).get("opportunities") or []
        card = next((item for item in cards if item.get("id") == opportunity_id), None)
        if not card:
            abort(404)
        card = dict(card)
        card["url"] = safe_http_url(card.get("url") or "")
        card["official_url"] = safe_http_url(card.get("official_url") or "")
        return render_template("opportunity.html", title=card.get("role") or "Opportunity", active="search", card=card)

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
            preferred_skills=", ".join(settings.preferred_skills),
            preferred=", ".join(settings.preferred_companies),
            excluded=", ".join(settings.excluded_companies),
            weights=settings.match_weights,
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
        return render_template(
            "profile.html",
            title="Profile",
            active="profile",
            profile=profile,
            cv_name=Path(profile.cv_path).name if profile.cv_path else "",
            flash=pop_flash(),
        )

    @app.post("/profile")
    def save_profile_page():
        home_path = current_home()
        payload, error, warnings = validate_profile_fields(request.form)
        if error:
            set_flash(error)
            return redirect(url_for("profile_page"))
        profile = load_profile(home_path)
        for key, value in payload.items():
            setattr(profile, key, value)
        note = "Profile saved."
        if warnings:
            note += " Some education or experience lines do not use the | format."
        save_profile(home_path, profile)
        set_flash(note)
        return redirect(url_for("profile_page"))

    @app.post("/profile/resume")
    def replace_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        note = _save_cv(home_path, profile)
        save_profile(home_path, profile)
        set_flash(note or "Resume replaced.")
        return redirect(url_for("profile_page"))

    @app.post("/profile/reanalyze")
    def reanalyze():
        home_path = current_home()
        profile = load_profile(home_path)
        if not profile.cv_text.strip():
            set_flash("Upload a resume with readable text first.")
            return redirect(url_for("profile_page"))
        apply_extraction(profile, extract_resume(profile.cv_text), overwrite=True)
        profile.onboarded = False
        save_profile(home_path, profile)
        set_flash("The resume was read again. Confirm what it actually says.")
        return redirect(url_for("onboarding"))

    @app.post("/profile/resume/delete")
    def delete_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        if profile.cv_path:
            Path(profile.cv_path).unlink(missing_ok=True)
        profile.cv_path = ""
        profile.cv_text = ""
        save_profile(home_path, profile)
        set_flash("Resume deleted from this account.")
        return redirect(url_for("profile_page"))

    @app.post("/account/delete")
    def delete_account():
        home_path = current_home()
        user_id = session.get("user_id")
        if user_id == "local":
            for name in ("profile.json", "settings.json", "searches.json", "state.json"):
                (home_path / name).unlink(missing_ok=True)
            shutil.rmtree(home_path / "cv", ignore_errors=True)
        else:
            shutil.rmtree(home_path, ignore_errors=True)
        session.pop("user_id", None)
        session.pop("user_name", None)
        session.pop("user_email", None)
        return redirect(url_for("landing"))

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html", title="Privacy", active="")

    @app.get("/terms")
    def terms():
        return render_template("terms.html", title="Terms", active="")

    @app.get("/api/status")
    def status():
        if not signed_in():
            abort(403)
        return jsonify(_snapshot(current_home()))

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", title="Form expired", message="Reload the page and submit the form again."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", title="Not available", message="This page is only available on this computer."), 403

    @app.errorhandler(404)
    def missing(_error):
        return render_template("error.html", title="Not found", message="That page does not exist."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", title="File too large", message="The upload is larger than 8 MB."), 413

    return app


def _preferences_from_form(settings, form) -> None:
    kinds = [item for item in form.getlist("employment_choice") if item]
    if len(kinds) == 1:
        settings.employment = kinds[0]
    elif len(kinds) > 1:
        settings.employment = "any"
    place = (form.get("workplace") or "").strip()
    if place in {"any", "remote", "hybrid", "onsite"}:
        settings.workplace = place
        settings.allow_hybrid = place in {"hybrid", "any"}
    if (form.get("location") or "").strip():
        settings.location = form.get("location").strip()
    if (form.get("minimum_stipend") or "").strip():
        try:
            settings.minimum_stipend = max(0, float(form.get("minimum_stipend")))
        except ValueError:
            pass
    if (form.get("roles") or "").strip():
        from jobagent.textutil import split_csv

        settings.roles = split_csv(form.get("roles"))
    if (form.get("sector") or "").strip():
        from jobagent.textutil import split_csv

        settings.sectors = split_csv(form.get("sector"))
    settings.avoid_unpaid = (form.get("avoid_unpaid") or "") in {"1", "on", "true", "yes"}
    settings.avoid_relocation = (form.get("avoid_relocation") or "") in {"1", "on", "true", "yes"}
    settings.avoid_sales = (form.get("avoid_sales") or "") in {"1", "on", "true", "yes"}
    settings.avoid_video = (form.get("avoid_video") or "") in {"1", "on", "true", "yes"}
    settings.avoid_above_level = (form.get("avoid_above_level") or "") in {"1", "on", "true", "yes"}
    note = (form.get("other_preferences") or "").strip()
    if note:
        from jobagent.intelligence import apply_natural_request

        apply_natural_request(settings, note)


def _profile_view(profile) -> dict:
    return {
        "name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "education": profile.degree or profile.education_raw,
        "college": profile.college,
        "skills": profile.skills,
        "projects": profile.projects,
    }


def _snapshot(home: Path) -> dict:
    state = load_state(home)
    return {
        "running": bool(state.get("running")),
        "search_status": state.get("search_status") or "stopped",
        "found": state.get("found") or 0,
        "discovered": state.get("discovered") or state.get("found") or 0,
        "rejected": state.get("rejected") or 0,
        "qualified": state.get("qualified") or 0,
        "strong_matches": state.get("strong_matches") or state.get("qualified") or 0,
        "status_line": state.get("status_line") or "",
        "phase": state.get("phase") or "",
        "query": state.get("query") or "",
        "warnings": state.get("warnings") or [],
        "rejection_counts": state.get("rejection_counts") or {},
        "opportunities": state.get("opportunities") or [],
        "source_report": state.get("source_report") or [],
        "analyzed": state.get("analyzed") or 0,
        "active": state.get("active") or 0,
        "duplicates": state.get("duplicates") or 0,
        "final_count": state.get("final_count") or 0,
        "relaxed": bool(state.get("relaxed")),
    }


def _save_cv(home: Path, profile) -> str:
    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return "Choose a PDF, DOCX, TXT, or MD resume."
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in CV_EXTENSIONS:
        return "Use a PDF, DOCX, TXT, or MD file."
    blob = upload.read()
    if len(blob) > 5 * 1024 * 1024:
        return "The resume must be 5 MB or smaller."
    dest = home / "cv" / f"resume{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    profile.cv_path = str(dest)
    profile.cv_text = extract_cv_text(dest)
    if not profile.cv_text.strip():
        return "The file was saved, but no text could be read. A scanned PDF will not score well."
    return ""


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
    print(f"AI Job Finder is running on this computer: http://{host}:{port}", flush=True)
    application.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
