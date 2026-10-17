"""Gmail OAuth for a one-time code only. The mailbox password is never stored or requested."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobagent.paths import file_lock
from jobagent.textutil import clean_html

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
AGGREGATORS = {
    "remotive.com",
    "remoteok.com",
    "arbeitnow.com",
    "themuse.com",
    "jobicy.com",
    "himalayas.app",
}
_SKIP_CODE = re.compile(r"postal|zip|area|country|promo|referral|\bjob\b", re.I)


class GmailNotConnected(Exception):
    """Raised when a one-time code is required and Gmail is not available."""


def credentials_path(home: Path) -> Path:
    return home / "gmail_client_secret.json"


def token_path(home: Path) -> Path:
    return home / "gmail_token.json"


def valid_client_file(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    block = data.get("installed") or data.get("web")
    return isinstance(block, dict) and bool(block.get("client_id"))


def gmail_connected(home: Path) -> bool:
    path = token_path(home)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("refresh_token") or data.get("token"))


def connect_gmail(home: Path) -> None:
    source = credentials_path(home)
    if not valid_client_file(source):
        raise GmailNotConnected("Upload the Gmail OAuth client JSON on the Profile page first.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(source), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    path = token_path(home)
    with file_lock(path):
        path.write_text(creds.to_json(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def disconnect_gmail(home: Path) -> None:
    path = token_path(home)
    with file_lock(path):
        if path.exists():
            path.unlink()


def mail_domains(url: str) -> list[str]:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    domains: list[str] = []
    for suffix in ("greenhouse.io", "lever.co", "ashbyhq.com"):
        if host.endswith(suffix):
            domains.append(suffix)
    parts = host.split(".")
    if len(parts) >= 2:
        domains.append(".".join(parts[-2:]))
    unique: list[str] = []
    for domain in domains:
        if domain and domain not in unique:
            unique.append(domain)
    return unique


def build_query(domains: list[str], started: datetime) -> str:
    yesterday = (started.astimezone(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
    subject = '(otp OR "verification code" OR "one-time code" OR "one time code" OR "security code" OR "login code")'
    query = f"after:{yesterday} {subject}"
    usable = [domain for domain in domains if domain and domain not in AGGREGATORS]
    if usable:
        query += " (" + " OR ".join(f"from:{domain}" for domain in usable[:5]) + ")"
    return query


def extract_otp(text: str) -> str | None:
    if not text:
        return None
    patterns = (
        re.compile(
            r"(?:one[- ]time(?: password)?|otp|verification code|security code|login code|sign[- ]in code|confirmation code)"
            r"(?:\s+is|\s+code)?[^0-9]{0,32}([0-9]{4,8})",
            re.I,
        ),
        re.compile(r"\b([0-9]{4,8})\b[^0-9]{0,24}(?:is your|verification|one[- ]time|otp|security code)", re.I),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1)
    for match in re.finditer(r"\bcode\s*(?:is|:)\s*([0-9]{4,8})\b", text, re.I):
        prefix = text[max(0, match.start() - 16) : match.start()]
        if _SKIP_CODE.search(prefix):
            continue
        return match.group(1)
    return None


def _decode(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", "replace")


def message_text(payload: dict) -> str:
    plains: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plains.append(_decode(data))
        elif data and mime == "text/html":
            html_parts.append(clean_html(_decode(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return "\n".join(plains) if plains else "\n".join(html_parts)


def fetch_otp(home: Path, domains: list[str], started: datetime) -> str | None:
    if not gmail_connected(home):
        raise GmailNotConnected("Connect Gmail on the Profile page. Your Gmail password is never stored.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GmailNotConnected("Gmail libraries are not installed.") from exc
    path = token_path(home)
    with file_lock(path):
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json(), encoding="utf-8")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    query = build_query(domains, started)
    listed = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    messages = listed.get("messages") or []
    threshold = started.timestamp() - 30
    candidates = []
    for item in messages:
        meta = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        internal = int(meta.get("internalDate") or 0) / 1000
        if internal < threshold:
            continue
        candidates.append(meta)
    candidates.sort(key=lambda message: int(message.get("internalDate") or 0), reverse=True)
    for meta in candidates:
        full = service.users().messages().get(userId="me", id=meta["id"], format="full").execute()
        code = extract_otp(message_text(full.get("payload") or {}))
        if code:
            return code
    return None
