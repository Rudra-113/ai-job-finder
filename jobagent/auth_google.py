"""Google sign-in. Mailbox access is not requested."""

from __future__ import annotations

import json
import os
from pathlib import Path

SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)


def client_config(home: Path) -> dict | None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return _web_config(client_id, client_secret)
    path = home / "google_oauth_client.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    web = data.get("web") if isinstance(data, dict) else None
    if not isinstance(web, dict) or not web.get("client_id") or not web.get("client_secret"):
        return None
    return {"web": web}


def google_ready(home: Path) -> bool:
    return client_config(home) is not None


def _web_config(client_id: str, client_secret: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


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
