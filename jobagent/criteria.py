"""Hard rules taken from the settings page. A miss here is a skip, not a guess."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from jobagent.models import Job
from jobagent.safety import mentions_fee
from jobagent.settings import Settings
from jobagent.textutil import (
    is_full_time,
    normalize_period,
    parse_salary_text,
    skill_in_text,
    to_monthly,
)

MAX_LISTING_AGE_DAYS = 30

_SECTOR_ALIASES = {
    "cybersecurity": ("cybersecurity", "cyber security", "information security", "infosec", "application security", "network security"),
    "cyber": ("cybersecurity", "cyber security", "information security"),
    "security": ("cybersecurity", "information security", "infosec", "application security", "security engineer"),
}

_TINY = {"and", "or", "the", "of", "for", "a", "an", "to", "in", "on"}
_CLOSED = re.compile(
    r"no longer accepting|position has been filled|this (?:job|position|role) has expired|applications? (?:are|is) closed",
    re.I,
)
_UNPAID = re.compile(
    r"\bunpaid\b|\bno stipend\b|\bwithout (?:a )?stipend\b|\bexpenses only\b|\bacademic credit only\b|"
    r"\bvolunteer (?:internship|role|position|opportunity|program)\b|"
    r"(?:salary|stipend|pay)\s*[:\-]?\s*(?:\$|€|£|₹)?\s*0\b",
    re.I,
)


def _terms(phrase: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9+#.]+", phrase.casefold()) if part and part not in _TINY]


def term_present(term: str, folded: str, original: str) -> bool:
    if term == "it":
        return bool(re.search(r"\bIT\b", original) or "information technology" in folded)
    if len(term) >= 6:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}", folded) is not None
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", folded) is not None


def sector_matches(job: Job, sectors: list[str]) -> bool:
    if not sectors:
        return False
    original = "\n".join([job.title, job.location, job.category, " ".join(job.tags), job.description])
    folded = original.casefold()
    for sector in sectors:
        phrase = sector.casefold().strip()
        for alias in _SECTOR_ALIASES.get(phrase, ()):
            if alias in folded:
                return True
        terms = _terms(sector)
        if terms and all(term_present(term, folded, original) for term in terms):
            return True
    return False


def token_in(token: str, hay: str) -> bool:
    if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", hay):
        return True
    if len(token) >= 5 and re.search(rf"(?<![a-z0-9]){re.escape(token)}", hay):
        return True
    return False


def role_tokens(role: str) -> list[str]:
    return _terms(role)


def role_matches(job: Job, roles: list[str]) -> bool:
    hay = f"{job.title} {job.employment} {' '.join(job.tags)}".casefold()
    for role in roles:
        tokens = role_tokens(role)
        if not tokens:
            continue
        if role.casefold().strip() in hay:
            return True
        hits = sum(1 for token in tokens if token_in(token, hay))
        if hits / len(tokens) >= 0.67:
            return True
    return False


def role_in_title(job: Job, roles: list[str]) -> bool:
    title = job.title.casefold()
    for role in roles:
        tokens = role_tokens(role)
        if tokens and all(token_in(token, title) for token in tokens):
            return True
    return False


def listing_blob(job: Job) -> str:
    return f"{job.title}\n{job.description}\n{' '.join(job.tags)}\n{job.category}"


def required_skills_listed(job: Job, skills: list[str]) -> bool:
    blob = listing_blob(job)
    return all(skill_in_text(skill, blob) for skill in skills)


def company_named(company: str, names: list[str]) -> bool:
    folded = company.casefold()
    for name in names:
        token = name.casefold().strip()
        if token and token in folded:
            return True
    return False


def is_unpaid(text: str) -> bool:
    folded = text or ""
    if re.search(r"\b(no|not)\s+unpaid\b", folded, re.I):
        folded = re.sub(r"\b(no|not)\s+unpaid\b", " ", folded, flags=re.I)
    return bool(_UNPAID.search(folded))


def infer_workplace(job: Job) -> str:
    if job.workplace in {"remote", "onsite", "hybrid"}:
        return job.workplace
    blob = f"{job.location} {job.title} {job.employment}".casefold()
    if "hybrid" in blob:
        return "hybrid"
    if job.remote is True or re.search(r"\bremote\b|\bwork from home\b|\bwfh\b", blob):
        return "remote"
    if job.remote is False:
        return "onsite"
    return "unknown"


def place_match(wanted: str, actual: str) -> bool:
    wanted_cf = wanted.casefold().strip()
    actual_cf = actual.casefold().strip()
    if not wanted_cf:
        return True
    if not actual_cf:
        return False
    if len(wanted_cf) <= 3:
        return re.search(rf"(?<![a-z]){re.escape(wanted_cf)}(?![a-z])", actual_cf) is not None
    if wanted_cf in actual_cf:
        return True
    if len(actual_cf) <= 3:
        return re.search(rf"(?<![a-z]){re.escape(actual_cf)}(?![a-z])", wanted_cf) is not None
    return False


def restriction_allows(wanted: str, actual: str) -> bool:
    actual_cf = (actual or "").casefold().strip()
    if not actual_cf or actual_cf in {"remote", "remote job"}:
        return True
    if re.search(r"\b(worldwide|anywhere|global)\b", actual_cf):
        return True
    return place_match(wanted, actual)


def workplace_problem(job: Job, settings: Settings) -> str | None:
    preference = settings.workplace
    place = infer_workplace(job)
    allow_hybrid = bool(getattr(settings, "allow_hybrid", False))
    if preference == "remote" and place == "onsite":
        return "On-site role while remote is selected"
    if preference == "remote" and place == "hybrid" and not allow_hybrid:
        return "Hybrid is off. Enable hybrid in Settings to include it."
    if preference == "onsite" and place == "remote":
        return "Not the workplace type you selected"
    if preference == "hybrid" and place == "onsite":
        return "Not the workplace type you selected"
    wanted = settings.location.strip()
    if not wanted:
        return None
    if not (job.location or "").strip():
        return None
    if place in {"remote", "unknown"} and preference in {"remote", "any", "hybrid"}:
        if restriction_allows(wanted, job.location):
            return None
        return "Location does not match"
    if place_match(wanted, job.location):
        return None
    return "Location does not match"


def structured_monthly(job: Job) -> float | None:
    period = normalize_period(job.salary_period)
    if not period:
        return None
    amount = job.salary_min if job.salary_min is not None else job.salary_max
    if job.salary_min is not None and job.salary_max is not None:
        amount = min(job.salary_min, job.salary_max)
    if amount is None:
        return None
    context = f"{job.employment}\n{job.salary_text}\n{job.description[:800]}"
    return to_monthly(amount, period, is_full_time(context) or period in {"month", "year"})


def monthly_pay(job: Job) -> float | None:
    monthly = structured_monthly(job)
    if monthly is None:
        monthly = parse_salary_text(job.salary_text, job.employment) or parse_salary_text(
            job.description[:4000], job.employment
        )
    return monthly


def compensation_label(job: Job) -> str:
    text = f"{job.title}\n{job.salary_text}\n{job.description[:4000]}"
    if is_unpaid(text):
        return "unpaid"
    if monthly_pay(job) is None:
        return "unknown"
    return "stated"


def stipend_problem(job: Job, minimum: float) -> str | None:
    label = compensation_label(job)
    if label == "unpaid":
        return "Unpaid"
    if label == "unknown":
        return None
    monthly = monthly_pay(job)
    if monthly is not None and minimum > 0 and round(monthly, 2) < minimum:
        return "Pay is below your minimum"
    return None


def posting_age_problem(job: Job, max_days: int, now: datetime) -> str | None:
    if not max_days or job.posted_at is None:
        return None
    posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
    days = (now.date() - posted.astimezone(timezone.utc).date()).days
    if days > max_days:
        return "Posted too long ago"
    return None


def age_problem(job: Job, now: datetime) -> str | None:
    if job.deadline is not None:
        deadline = job.deadline if job.deadline.tzinfo else job.deadline.replace(tzinfo=timezone.utc)
        if deadline.astimezone().date() < now.astimezone().date():
            return "Deadline passed"
    if _CLOSED.search(job.description or ""):
        return "Listing is closed"
    return None
