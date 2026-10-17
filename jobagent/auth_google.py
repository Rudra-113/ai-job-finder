"""Google sign-in. Mailbox access is not requested."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)
_LOOPBACK = {"127.0.0.1", "localhost"}


def client_config(home: Path) -> dict | None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return _web_config(client_id, client_secret)
    for name in ("google_oauth_client.json", "gmail_client_secret.json"):
        loaded = _read_client(home / name)
        if loaded:
            return loaded
    return None


def google_ready(home: Path) -> bool:
    return client_config(home) is not None


def client_kind(config: dict | None) -> str:
    if not config:
        return ""
    if "web" in config:
        return "web"
    if "installed" in config:
        return "installed"
    return ""


def sign_in_redirect(home: Path, public_base: str, port: int) -> str:
    """Pick a redirect URI this OAuth client is allowed to use.

    A desktop Gmail client accepts only a loopback address. A web client can
    return to the address the browser is already using.
    """
    config = client_config(home) or {}
    kind = client_kind(config)
    callback = public_base.rstrip("/") + "/auth/google/callback"
    if kind == "installed":
        return f"http://127.0.0.1:{int(port)}/auth/google/callback"
    registered = _registered(config)
    if callback in registered or not registered:
        return callback
    host = urlsplit(public_base).hostname or ""
    for item in registered:
        if urlsplit(item).hostname == host:
            return item if item.endswith("/auth/google/callback") else callback
    return callback


def loopback_return(url: str) -> bool:
    parsed = urlsplit((url or "").strip())
    return (
        parsed.scheme == "http"
        and (parsed.hostname or "") in _LOOPBACK
        and parsed.path.rstrip("/") == "/auth/google/callback"
        and bool(parsed.query)
    )


def _web_config(client_id: str, client_secret: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _read_client(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("web", "installed"):
        block = data.get(key)
        if isinstance(block, dict) and block.get("client_id") and block.get("client_secret"):
            return {key: block}
    return None


def _registered(config: dict) -> list[str]:
    block = config.get("web") or config.get("installed") or {}
    raw = block.get("redirect_uris") or []
    return [str(item) for item in raw if item]


def authorization_url(home: Path, redirect_uri: str) -> tuple[str, str]:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(client_config(home), scopes=list(SCOPES))
    flow.redirect_uri = redirect_uri
    url, state = flow.authorization_url(
        access_type="online",
        prompt="select_account",
        include_granted_scopes="false",
    )
    return url, state


def exchange_identity(home: Path, redirect_uri: str, authorization_response: str) -> dict:
    """Return sub, email, and name. The token is not written to disk."""
    # Google returns the same scopes in a different order. That is still this sign-in.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(client_config(home), scopes=list(SCOPES))
    flow.redirect_uri = redirect_uri
    flow.fetch_token(authorization_response=authorization_response)
    session = flow.authorized_session()
    payload = session.get("https://openidconnect.googleapis.com/v1/userinfo", timeout=15).json()
    sub = str(payload.get("sub") or "").strip()
    email = str(payload.get("email") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not sub or not email:
        raise ValueError("Google did not return an account id.")
    return {"sub": sub, "email": email, "name": name}
