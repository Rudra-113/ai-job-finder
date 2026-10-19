"""AI Job Finder API. The browser UI is a separate static site."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session
from werkzeug.datastructures import ImmutableMultiDict

from jobagent.accounts import user_home
from jobagent.history import find_search, load_history
from jobagent.logsetup import configure
from jobagent.paths import default_home, load_secret_key
from jobagent.profile import extract_cv_text, load_profile, save_profile, validate_profile_fields
from jobagent.resume_extract import apply_extraction, extract_resume
from jobagent.runner import AgentService, load_state, write_state
from jobagent.settings import apply_main_fields, apply_settings_form, load_settings, save_settings
from jobagent.textutil import safe_http_url

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"
CV_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def bind_host() -> str:
    return os.environ.get("BIND_HOST", "0.0.0.0")


def host_allowed(host: str) -> bool:
    name = (host or "").split(":")[0].strip().lower()
    configured = {
        item.strip().lower()
        for item in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
        if item.strip()
    }
    if "*" in configured or name in configured:
        return True
    external = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
    if external and name == external:
        return True
    if os.environ.get("RENDER") == "true" and name.endswith(".onrender.com"):
        return True
    return False


def frontend_origins() -> list[str]:
    return [item.strip().rstrip("/") for item in os.environ.get("FRONTEND_ORIGIN", "").split(",") if item.strip()]


def page_url(path: str) -> str:
    origins = frontend_origins()
    if origins:
        return origins[0] + path
    return path


def create_app(home: Path | None = None) -> Flask:
    home = Path(home) if home is not None else default_home()
    home.mkdir(parents=True, exist_ok=True)
    configure(home)
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "").strip() or load_secret_key(home / "secret.key")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    production = os.environ.get("RENDER") == "true" or os.environ.get("APP_ENV") == "production"
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "None" if production else "Lax")
    secure = os.environ.get("SESSION_COOKIE_SECURE", "1" if production else "0")
    app.config["SESSION_COOKIE_SECURE"] = secure.strip().lower() in {"1", "true", "yes"}
    # The site and the API are on different hosts. A partitioned cookie can be stored
    # for that pair; the visitor header below still works when the cookie is blocked.
    app.config["SESSION_COOKIE_PARTITIONED"] = production
    app.extensions["home"] = home
    app.extensions["agent"] = AgentService(home)
    app.extensions["serve_frontend"] = os.environ.get("SERVE_FRONTEND", "").strip() in {"1", "true", "yes"}

    def root_home() -> Path:
        return app.extensions["home"]

    def _visitor_token(user_id: str) -> str:
        key = app.config["SECRET_KEY"]
        secret = key.encode() if isinstance(key, str) else bytes(key)
        return hmac.new(secret, user_id.encode(), hashlib.sha256).hexdigest()

    def _valid_visitor(user_id: str) -> bool:
        return bool(re.fullmatch(r"anon_[0-9a-f]{32}", user_id or ""))

    def _same_token(left: str, right: str) -> bool:
        if not left or not right:
            return False
        return hmac.compare_digest(left, right)

    def _adopt_visitor() -> None:
        if session.get("user_id"):
            return
        visitor = (request.headers.get("X-Visitor-Id") or "").strip()
        token = (request.headers.get("X-CSRF-Token") or "").strip()
        if _valid_visitor(visitor) and _same_token(token, _visitor_token(visitor)):
            session["user_id"] = visitor
            session["csrf"] = token

    def _posted_csrf() -> str:
        token = (request.headers.get("X-CSRF-Token") or "").strip()
        if token:
            return token
        if request.is_json:
            body = request.get_json(silent=True) or {}
            if isinstance(body, dict):
                return str(body.get("csrf") or "")
        return str(request.form.get("csrf") or "")

    def ensure_visitor() -> None:
        if session.get("user_id") or request.path == "/api/health":
            return
        _adopt_visitor()
        if session.get("user_id"):
            return
        session["user_id"] = "anon_" + secrets.token_hex(16)
        session["csrf"] = _visitor_token(session["user_id"])

    def current_home() -> Path:
        ensure_visitor()
        return user_home(root_home(), session.get("user_id") or "")

    def agent() -> AgentService:
        return app.extensions["agent"]

    def wants_json() -> bool:
        if request.path.startswith("/api/"):
            return True
        if request.is_json:
            return True
        accept = request.headers.get("Accept", "")
        return "application/json" in accept

    def ok(**payload):
        body = {"ok": True}
        body.update(payload)
        return jsonify(body)

    def form_data() -> ImmutableMultiDict:
        if request.is_json:
            raw = request.get_json(silent=True) or {}
            pairs = []
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if isinstance(value, list):
                        for item in value:
                            pairs.append((str(key), "" if item is None else str(item)))
                    elif isinstance(value, bool):
                        if value:
                            pairs.append((str(key), "1"))
                    elif value is not None:
                        pairs.append((str(key), str(value)))
            return ImmutableMultiDict(pairs)
        return request.form

    @app.after_request
    def cors(response):
        origin = (request.headers.get("Origin") or "").rstrip("/")
        allowed = set(frontend_origins())
        if origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token, X-Visitor-Id, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.before_request
    def guard():
        if not host_allowed(request.host):
            return jsonify({"ok": False, "error": "This host is not allowed."}), 403
        if request.method == "OPTIONS":
            return ("", 204)
        _adopt_visitor()
        if not session.get("user_id") and request.path != "/api/health" and request.method != "POST":
            session["user_id"] = "anon_" + secrets.token_hex(16)
            session["csrf"] = _visitor_token(session["user_id"])
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST":
            # A cross-site call may not send the cookie. The signed visitor header is the session.
            if not session.get("user_id"):
                return jsonify({"ok": False, "error": "Reload the page and submit the form again."}), 400
            if not _same_token(_posted_csrf(), session.get("csrf") or ""):
                return jsonify({"ok": False, "error": "Reload the page and submit the form again."}), 400
        return None

    def _public_profile(profile) -> dict:
        data = profile.to_dict()
        data.pop("cv_text", None)
        data.pop("cv_path", None)
        data["cv_name"] = Path(profile.cv_path).name if profile.cv_path else ""
        data["has_resume"] = bool((profile.cv_text or "").strip() or profile.cv_path)
        return data

    def _settings_payload(settings) -> dict:
        data = settings.to_dict()
        data["sector"] = ", ".join(settings.sectors)
        data["role_text"] = ", ".join(settings.roles)
        data["required_skills_text"] = ", ".join(settings.required_skills)
        data["preferred_skills_text"] = ", ".join(settings.preferred_skills)
        data["preferred_companies_text"] = ", ".join(settings.preferred_companies)
        data["excluded_companies_text"] = ", ".join(settings.excluded_companies)
        return data

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/session")
    def session_info():
        return jsonify(
            {
                "logged_in": bool(session.get("user_id")),
                "visitor_id": session.get("user_id") or "",
                "user_name": session.get("user_name") or "",
                "user_email": session.get("user_email") or "",
                "csrf": session.get("csrf") or "",
            }
        )

    @app.get("/auth")
    @app.get("/auth.html")
    def auth_page():
        return redirect(page_url("/onboarding.html"))

    @app.get("/api/home")
    def home_state():
        home_path = current_home()
        profile = load_profile(home_path)
        settings = load_settings(home_path)
        if not profile.onboarded and profile.problem() is None and settings.sectors and settings.roles:
            profile.onboarded = True
            save_profile(home_path, profile)
        snap = _snapshot(home_path)
        return jsonify(
            {
                "profile": _public_profile(profile),
                "needs_onboarding": not profile.onboarded,
                "settings": _settings_payload(settings),
                "history": [
                    {"id": item.get("id"), "query": item.get("query"), "final_count": item.get("final_count") or 0, "created": item.get("created") or ""}
                    for item in load_history(home_path)[:8]
                ],
                "search": snap,
            }
        )

    @app.get("/api/status")
    def status():
        return jsonify(_snapshot(current_home()))

    @app.post("/api/search")
    def start_search():
        home_path = current_home()
        settings = load_settings(home_path)
        error = apply_main_fields(settings, form_data())
        if error:
            return jsonify({"ok": False, "error": error}), 400
        save_settings(home_path, settings)
        problem = load_profile(home_path).problem()
        if problem:
            return jsonify({"ok": False, "error": problem, "next": "/onboarding.html"}), 400
        if agent().running():
            return jsonify({"ok": False, "error": "A search is already running."}), 409
        agent().start(home_path, (form_data().get("request") or "").strip())
        return ok()

    @app.post("/api/stop")
    def stop():
        agent().request_stop()
        return ok(message="Stopping the search. No application is sent.")

    @app.post("/api/history/<search_id>/open")
    def open_history(search_id: str):
        home_path = current_home()
        row = find_search(home_path, search_id)
        if not row:
            return jsonify({"ok": False, "error": "That search is not in this browser."}), 404
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
            relaxed=False,
            phase="",
        )
        return ok()

    @app.get("/api/opportunities/<opportunity_id>")
    def opportunity(opportunity_id: str):
        if not re.fullmatch(r"[0-9a-f]{8,64}", opportunity_id):
            abort(404)
        cards = load_state(current_home()).get("opportunities") or []
        card = next((item for item in cards if item.get("id") == opportunity_id), None)
        if not card:
            abort(404)
        card = dict(card)
        card["url"] = safe_http_url(card.get("url") or "")
        card["apply_url"] = safe_http_url(card.get("apply_url") or card.get("url") or "")
        card["official_url"] = safe_http_url(card.get("official_url") or "")
        return jsonify(card)

    @app.get("/api/settings")
    def settings_page():
        return jsonify(_settings_payload(load_settings(current_home())))

    @app.post("/api/settings")
    def save_settings_page():
        settings, error = apply_settings_form(form_data())
        if error:
            return jsonify({"ok": False, "error": error}), 400
        save_settings(current_home(), settings)
        return ok(message="Settings saved.", settings=_settings_payload(settings))

    @app.get("/api/profile")
    def profile_page():
        return jsonify(_public_profile(load_profile(current_home())))

    @app.post("/api/profile")
    def save_profile_page():
        payload, error, warnings = validate_profile_fields(form_data())
        if error:
            return jsonify({"ok": False, "error": error}), 400
        profile = load_profile(current_home())
        for key, value in payload.items():
            setattr(profile, key, value)
        save_profile(current_home(), profile)
        note = "Profile saved."
        if warnings:
            note += " Some education or experience lines do not use the | format."
        return ok(message=note, profile=_public_profile(profile))

    @app.post("/api/profile/resume")
    def replace_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        note = _save_cv(home_path, profile)
        save_profile(home_path, profile)
        if note:
            return jsonify({"ok": False, "error": note, "profile": _public_profile(profile)}), 400
        return ok(message="Resume replaced.", profile=_public_profile(profile))

    @app.post("/api/profile/reanalyze")
    def reanalyze():
        home_path = current_home()
        profile = load_profile(home_path)
        if not profile.cv_text.strip():
            return jsonify({"ok": False, "error": "Upload a resume with readable text first."}), 400
        apply_extraction(profile, extract_resume(profile.cv_text), overwrite=True)
        profile.onboarded = False
        save_profile(home_path, profile)
        return ok(message="The resume was read again. Confirm what it actually says.", next="/onboarding.html")

    @app.post("/api/profile/resume/delete")
    def delete_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        if profile.cv_path:
            Path(profile.cv_path).unlink(missing_ok=True)
        profile.cv_path = ""
        profile.cv_text = ""
        save_profile(home_path, profile)
        return ok(message="Resume deleted.", profile=_public_profile(profile))

    @app.get("/api/onboarding")
    def onboarding():
        home_path = current_home()
        profile = load_profile(home_path)
        settings = load_settings(home_path)
        return jsonify({"profile": _public_profile(profile), "settings": _settings_payload(settings), "extracted": _profile_view(profile)})

    @app.post("/api/onboarding/resume")
    def onboarding_resume():
        home_path = current_home()
        profile = load_profile(home_path)
        note = _save_cv(home_path, profile)
        if profile.cv_text:
            apply_extraction(profile, extract_resume(profile.cv_text), overwrite=False)
        save_profile(home_path, profile)
        if note and not profile.cv_text:
            return jsonify({"ok": False, "error": note}), 400
        return ok(message=note or "Resume read. Check the profile before continuing.", profile=_public_profile(profile))

    @app.post("/api/onboarding/confirm")
    def onboarding_confirm():
        home_path = current_home()
        incoming = form_data()
        payload, error, _warnings = validate_profile_fields(incoming)
        if error:
            return jsonify({"ok": False, "error": error}), 400
        profile = load_profile(home_path)
        for key, value in payload.items():
            setattr(profile, key, value)
        profile.onboarded = True
        save_profile(home_path, profile)
        settings = load_settings(home_path)
        _preferences_from_form(settings, incoming)
        save_settings(home_path, settings)
        problem = profile.problem()
        if problem:
            profile.onboarded = False
            save_profile(home_path, profile)
            return jsonify({"ok": False, "error": problem}), 400
        return ok(next="/dashboard.html")

    @app.post("/api/account/delete")
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
        return ok(next="/index.html")

    def short_page():
        return redirect(page_url(request.path + ".html"))

    for page_name in ("dashboard", "profile", "settings", "onboarding", "opportunity", "privacy", "terms"):
        app.add_url_rule(f"/{page_name}", endpoint=f"page_{page_name}", view_func=short_page)

    @app.get("/")
    def landing():
        if app.extensions["serve_frontend"]:
            return send_from_directory(FRONTEND, "index.html")
        return jsonify({"service": "ai-job-finder", "health": "/api/health"})

    if app.extensions["serve_frontend"]:

        @app.get("/<path:asset>")
        def frontend_asset(asset: str):
            if asset.startswith("api/") or asset.startswith("auth/"):
                abort(404)
            target = (FRONTEND / asset).resolve()
            if FRONTEND.resolve() not in target.parents and target != FRONTEND.resolve():
                abort(404)
            if not target.is_file():
                abort(404)
            return send_from_directory(target.parent, target.name)

    @app.errorhandler(400)
    def bad_request(_error):
        return jsonify({"ok": False, "error": "Reload the page and submit the form again."}), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return jsonify({"ok": False, "error": "This host is not allowed."}), 403

    @app.errorhandler(404)
    def missing(_error):
        if wants_json() or "text/html" not in request.headers.get("Accept", ""):
            return jsonify({"ok": False, "error": "That page does not exist."}), 404
        page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found — AI Job Finder</title></head>
<body style="font-family:Segoe UI,system-ui,sans-serif;background:#f4f6f8;color:#172033;margin:0">
<main style="max-width:36rem;margin:4rem auto;padding:1.5rem;background:#fff;border-radius:16px">
<h1>That page was not found.</h1>
<p>The link does not match a page in AI Job Finder.</p>
<p><a href="/">Back to AI Job Finder</a></p>
</main></body></html>"""
        return page, 404, {"Content-Type": "text/html; charset=utf-8"}

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"ok": False, "error": "The upload is larger than 8 MB."}), 413

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


def _resume_bytes_ok(suffix: str, blob: bytes) -> str:
    if suffix == ".pdf" and not blob.startswith(b"%PDF"):
        return "That file is not a PDF."
    if suffix == ".docx" and not blob.startswith(b"PK"):
        return "That file is not a DOCX document."
    if suffix in {".txt", ".md"} and b"\x00" in blob[:8192]:
        return "That text file could not be read."
    return ""


def _save_cv(home: Path, profile) -> str:
    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return "Choose a PDF, DOCX, TXT, or MD resume."
    name = Path(upload.filename).name
    suffix = Path(name).suffix.lower()
    if suffix not in CV_EXTENSIONS:
        return "Use a PDF, DOCX, TXT, or MD file."
    blob = upload.read()
    if not blob:
        return "That resume file is empty."
    if len(blob) > 5 * 1024 * 1024:
        return "The resume must be 5 MB or smaller."
    kind = _resume_bytes_ok(suffix, blob)
    if kind:
        return kind
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
    for path in (ROOT / ".env", ROOT.parent / ".env"):
        if not path.is_file():
            continue
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
    raw_port = os.environ.get("PORT") or os.environ.get("JOBAGENT_PORT") or "47321"
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535.")
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes"}
    if os.environ.get("RENDER") == "true" or os.environ.get("APP_ENV") == "production":
        debug = False
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    application = create_app(default_home())
    print(f"AI Job Finder API is listening on {host}:{port}", flush=True)
    application.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
