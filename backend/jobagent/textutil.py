"""Text helpers shared by search, scoring, and pay checks."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobagent.models import Job

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t]+")
_BREAK = re.compile(r"(?i)<\s*br\s*/?>|</\s*p\s*>|</\s*div\s*>|</\s*li\s*>")
_ATS = re.compile(
    r"https?://[^\s\"'<>]+(?:greenhouse\.io|lever\.co|ashbyhq\.com)/[^\s\"'<>]+",
    re.I,
)
_TRACKING = {"gh_src", "lever-origin", "lever-source"}

STOPWORDS = {
    "about", "above", "after", "again", "against", "their", "there", "these",
    "those", "which", "while", "where", "would", "could", "should", "because",
    "before", "being", "between", "other", "under", "over", "into", "through",
    "during", "including", "include", "within", "without", "across", "another",
    "really", "using", "based", "strong", "ability", "looking", "seeking",
    "please", "apply", "applicant", "application", "company", "team", "role",
    "work", "working", "experience", "skills", "years", "year", "with", "from",
    "that", "this", "have", "will", "your", "what", "when", "requirements",
    "required", "preferred", "responsibilities", "responsibility", "opportunity",
    "position", "join", "our", "the", "and", "for", "you", "are", "job", "jobs",
    "new", "all", "can", "who", "its", "not", "but", "they", "them", "been",
    "more", "than", "also", "such", "per", "via", "any", "may", "well", "make",
    "makes", "making", "help", "helps", "high", "best", "great", "good", "able",
    "must", "need", "needs", "your", "we're", "were", "was", "has", "had",
}


def clean_html(raw: str) -> str:
    text = raw or ""
    for _ in range(2):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = _BREAK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = _SPACE.sub(" ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def parse_date(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip())
    ):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        try:
            return datetime.fromtimestamp(number, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                items.append(str(item.get("name") or item.get("title") or ""))
            else:
                items.append(str(item))
        return [item.strip() for item in items if item and item.strip()]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [part.strip(" '\"") for part in inner.split(",") if part.strip(" '\"")]
        return [part.strip() for part in text.split(",") if part.strip()]
    return [str(value).strip()]


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0:
        return None
    return number


def as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def normalize_period(value: str) -> str:
    text = (value or "").casefold()
    if any(token in text for token in ("hour", "hr")):
        return "hour"
    if "week" in text:
        return "week"
    if "month" in text:
        return "month"
    if any(token in text for token in ("year", "annual", "annum")):
        return "year"
    return ""


def parse_number(token: str | None) -> float | None:
    if not token:
        return None
    cleaned = token.replace(",", "").replace(" ", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kK])?", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2):
        number *= 1000
    return number


def period_in(text: str) -> str | None:
    folded = text.casefold()
    if re.search(r"per hour|an hour|/hr\b|hourly|per hr\b", folded):
        return "hour"
    if re.search(r"per week|weekly|/wk\b", folded):
        return "week"
    if re.search(r"per month|monthly|/mo\b|a month|per mo\b", folded):
        return "month"
    if re.search(r"per year|per annum|annually|yearly|/yr\b|a year|p\.a\b", folded):
        return "year"
    return None


def to_monthly(amount: float, period: str, full_time: bool) -> float | None:
    if amount <= 0:
        return None
    if period == "hour":
        if not full_time:
            return None
        return amount * 160
    if period == "week":
        if not full_time:
            return None
        return amount * 4
    if period == "month":
        return amount
    if period == "year":
        return amount / 12
    return None


def is_full_time(text: str) -> bool:
    return bool(re.search(r"full[- ]?time|\b40\s*hours\b", text or "", re.I))


_SALARY = re.compile(
    r"(?:USD|EUR|GBP|INR|CAD|AUD|\$|€|£|₹)?\s*"
    r"(\d[\d,]*(?:\.\d+)?\s*[kK]?)"
    r"(?:\s*(?:-|to)\s*(?:USD|EUR|GBP|INR|CAD|AUD|\$|€|£|₹)?\s*"
    r"(\d[\d,]*(?:\.\d+)?\s*[kK]?))?"
    r"([^\n.]{0,48})",
    re.I,
)
_MONEY_HINT = re.compile(
    r"[$€£₹]|\b(?:USD|EUR|GBP|INR|CAD|AUD|salary|stipend|compensation|paid)\b",
    re.I,
)


def parse_salary_text(text: str, employment: str = "") -> float | None:
    if not text:
        return None
    cleaned = text.replace("\u2013", "-").replace("\u2014", "-")
    context = f"{employment}\n{cleaned}"
    for match in _SALARY.finditer(cleaned):
        window = cleaned[max(0, match.start() - 40) : match.end() + 8]
        if not _MONEY_HINT.search(window):
            continue
        low = parse_number(match.group(1))
        high = parse_number(match.group(2)) if match.group(2) else None
        if low is None:
            continue
        amount = min(low, high) if high is not None else low
        tail = match.group(3) or ""
        before = cleaned[max(0, match.start() - 30) : match.start()]
        period = period_in(tail) or period_in(match.group(0)) or period_in(before)
        if period is None and amount >= 40000 and re.search(r"k", match.group(1), re.I):
            period = "year"
        if period is None:
            continue
        monthly = to_monthly(amount, period, is_full_time(context) or period in {"month", "year"})
        if monthly is not None and monthly > 0:
            return monthly
    return None


def skill_in_text(skill: str, text: str) -> bool:
    skill_cf = (skill or "").casefold().strip()
    if not skill_cf or not text:
        return False
    text_cf = text.casefold()
    if skill_cf in {"c++", "c#", "f#", ".net"}:
        return skill_cf in text_cf
    if len(skill_cf) <= 3 or len(skill_cf) < 6:
        return re.search(rf"(?<![a-z0-9]){re.escape(skill_cf)}(?![a-z0-9])", text_cf) is not None
    return re.search(rf"(?<![a-z0-9]){re.escape(skill_cf)}", text_cf) is not None


def distinctive(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9+#.]{3,}", (text or "").casefold())
    return {word for word in words if word not in STOPWORDS}


def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING
    ]
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def safe_http_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme in {"http", "https"} and parts.netloc:
        return url.strip()
    return ""


def normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").casefold()).strip()


def duplicate_key(job: Job) -> str:
    company = re.sub(r"[^a-z0-9]+", "", (job.company or "").casefold())
    title = normalized_title(job.title)
    if not company or not title:
        return ""
    return f"{company}|{title}"


def job_identity(job: Job) -> str:
    company = re.sub(r"[^a-z0-9]+", "", job.company.casefold())
    title = re.sub(r"[^a-z0-9]+", "", job.title.casefold())
    if not company or not title:
        return ""
    loc = re.sub(r"[^a-z0-9]+", "", (job.location or "").casefold())
    remoteish = job.workplace == "remote" or job.remote is True
    generic = {"", "remote", "worldwide", "anywhere", "global"}
    if remoteish:
        place = "remote" if loc in generic else f"remote-{loc}"
    else:
        place = loc or "unspecified"
    return f"{company}|{title}|{place}"


def find_ats_url(text: str) -> str:
    match = _ATS.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(").,]>\"'")


def workplace_from_location(location: str, remote_flag: bool | None = None) -> str:
    folded = (location or "").casefold()
    if "hybrid" in folded:
        return "hybrid"
    if remote_flag is True or re.search(r"\bremote\b", folded):
        return "remote"
    if remote_flag is False:
        return "onsite"
    return "unknown"


_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co|gmbh|plc|ag|sa|bv)\b",
    re.I,
)


def company_slugs(name: str) -> list[str]:
    cleaned = _SUFFIX.sub(" ", (name or "").casefold())
    hyphen = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    compact = hyphen.replace("-", "")
    slugs: list[str] = []
    for slug in (hyphen, compact):
        if len(slug) >= 2 and slug not in slugs:
            slugs.append(slug)
    return slugs
