"""One pass from raw listings to the best available opportunities.

Source adapters only fetch. Ranking, dedupe, availability, and resume matching
live here so each board is not a second search system.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from jobagent.criteria import age_problem, compensation_label, infer_workplace, monthly_pay, sector_in_title, sector_matches, stipend_problem, workplace_problem
from jobagent.filters import screen
from jobagent.matcher import evidence_text, potential_gaps, score_job
from jobagent.models import Job
from jobagent.profile import Profile
from jobagent.safety import mentions_fee
from jobagent.search import search_all_sources, search_queries
from jobagent.settings import Settings
from jobagent.textutil import canonical_url, duplicate_key, find_ats_url, safe_http_url, skill_in_text

_OFFICIAL_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com")
_VIDEO = re.compile(
    r"record a video|video response is required|video introduction is required|mandatory video|"
    r"one-way video interview|complete (?:a|the) video interview|live interview is required",
    re.I,
)
_DISPLAY = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "naukri": "Naukri",
    "unstop": "Unstop",
    "upwork": "Upwork",
    "greenhouse": "Company Careers",
    "lever": "Company Careers",
    "ashby": "Company Careers",
    "internshala": "Internshala",
    "remotive": "Remotive",
    "remoteok": "Remote OK",
    "arbeitnow": "Arbeitnow",
    "themuse": "The Muse",
    "jobicy": "Jobicy",
    "himalayas": "Himalayas",
}


def display_source(source: str) -> str:
    return _DISPLAY.get((source or "").casefold(), source or "Listing")


def apply_natural_request(settings: Settings, text: str) -> None:
    """Read a sentence such as '20 remote cybersecurity internships in India' onto settings."""
    raw = re.sub(r"\s+", " ", text or "").strip()
    if not raw:
        return
    folded = raw.casefold()
    count = re.search(r"\b(\d{1,3})\b", folded)
    if count and any(word in folded for word in ("find", "opportunity", "opportunities", "internship", "job", "role")):
        settings.opportunity_count = min(100, max(1, int(count.group(1))))
    if re.search(r"\bremote\b|\bwork from home\b|\bwfh\b", folded):
        settings.workplace = "remote"
    elif re.search(r"\bhybrid\b", folded):
        settings.workplace = "hybrid"
        settings.allow_hybrid = True
    elif re.search(r"\bon-?site\b|\bin office\b", folded):
        settings.workplace = "onsite"
    if re.search(r"\bindia\b", folded) and not settings.location.strip():
        settings.location = "India"
    money = re.search(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*)", folded, re.I)
    if money:
        settings.minimum_stipend = float(money.group(1).replace(",", ""))
    if "cyber" in folded and not any("cyber" in sector.casefold() for sector in settings.sectors):
        settings.sectors.append("cybersecurity")
    if re.search(r"\bpart[- ]time\b", folded):
        settings.employment = "part-time"
    elif re.search(r"\bcontract\b", folded):
        settings.employment = "contract"
    elif re.search(r"\bintern", folded):
        settings.employment = "intern"
        if not any("intern" in role.casefold() for role in settings.roles):
            settings.roles.append("cybersecurity intern" if "cyber" in folded else "intern")
    elif re.search(r"\bfull[- ]time\b", folded):
        settings.employment = "full-time"
    if re.search(r"\bunpaid\b", folded) and re.search(r"\b(no|not|don't|dont|avoid|without)\b", folded):
        settings.avoid_unpaid = True
    place = re.search(r"\bin ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", raw)
    if place and place.group(1).casefold() not in {"india", "remote", "office", "the"}:
        settings.location = place.group(1)
    preferred = re.search(r"prefer(?:ably|red)?\s+(.+)$", raw, re.I)
    if preferred:
        for part in re.split(r",| or | and ", preferred.group(1)):
            role = part.strip(" .")
            if len(role) >= 3 and role.casefold() not in {item.casefold() for item in settings.roles}:
                settings.roles.append(role)


def _official(url: str) -> bool:
    host = urlsplit(url or "").netloc.casefold()
    return any(token in host for token in _OFFICIAL_HOSTS)


def normalize_listing(job: Job) -> Job:
    job.url = safe_http_url(job.url) or job.url
    job.apply_url = safe_http_url(job.apply_url) or job.url
    ats = find_ats_url(job.description)
    if _official(job.apply_url) or _official(job.url):
        job.official_application_url = job.apply_url or job.url
        job.official_application_verified = True
    elif ats:
        job.official_application_url = ats
        job.official_application_verified = False
        job.apply_url = ats
    else:
        job.official_application_url = ""
        job.official_application_verified = False
    if not job.sources:
        job.sources = [display_source(job.source)]
    if not job.skills and job.tags:
        job.skills = list(job.tags[:12])
    return job


def availability(job: Job, now: datetime | None = None) -> str:
    if (job.availability_status or "").upper() == "EXPIRED":
        return "EXPIRED"
    if age_problem(job, now or datetime.now(timezone.utc)):
        return "EXPIRED"
    if (job.availability_status or "").upper() == "ACTIVE":
        return "ACTIVE"
    return "UNKNOWN"


def verify_page(job: Job, fetcher) -> str:
    """fetcher(url) -> status code and a text snippet, or None when the page cannot be read."""
    current = availability(job)
    if current == "EXPIRED" or fetcher is None:
        return current
    url = safe_http_url(job.official_application_url or job.apply_url or job.url)
    if not url:
        return "UNKNOWN"
    try:
        result = fetcher(url)
    except Exception:
        return "UNKNOWN"
    if not result:
        return "UNKNOWN"
    status, text = result
    folded = (text or "")[:8000].casefold()
    if status == 404 or age_problem(Job(job.source, job.company, job.title, url, description=folded), datetime.now(timezone.utc)):
        return "EXPIRED"
    if status in {401, 403, 429} or "captcha" in folded or "access denied" in folded:
        return "UNKNOWN"
    if status and 200 <= status < 400:
        if _official(url):
            job.official_application_verified = True
            job.official_application_url = url
        return "ACTIVE"
    return "UNKNOWN"


def polite_fetcher(url: str):
    try:
        response = httpx.get(
            url,
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": "PersonalJobAgent/1.0 (local; applications stay on this computer)"},
        )
    except httpx.HTTPError:
        return None
    return response.status_code, response.text[:8000]


def merge_duplicates(jobs: list[Job]) -> tuple[list[Job], int]:
    grouped: dict[str, Job] = {}
    removed = 0
    for job in jobs:
        key = duplicate_key(job) or safe_http_url(job.url)
        current = grouped.get(key)
        if current is None:
            grouped[key] = job
            continue
        removed += 1
        for name in job.sources:
            if name not in current.sources:
                current.sources.append(name)
        if len(job.description or "") > len(current.description or ""):
            current.description = job.description
        if not current.official_application_verified and (job.official_application_verified or _official(job.apply_url)):
            current.official_application_url = job.official_application_url or job.apply_url
            current.official_application_verified = True
            current.apply_url = job.apply_url or current.apply_url
        if not (current.salary_min or current.salary_text) and (job.salary_min or job.salary_text):
            current.salary_min = job.salary_min
            current.salary_max = job.salary_max
            current.salary_text = job.salary_text
            current.salary_period = job.salary_period
            current.salary_currency = job.salary_currency
        if not current.posted_at and job.posted_at:
            current.posted_at = job.posted_at
    return list(grouped.values()), removed


def why_matches(job: Job, profile: Profile) -> list[str]:
    blob = f"{job.title}\n{job.description}\n{' '.join(job.tags)}\n{' '.join(job.skills)}"
    reasons = []
    for skill in profile.skills:
        if skill_in_text(skill, blob) and skill not in reasons:
            reasons.append(skill)
    evidence = evidence_text(profile).casefold()
    for phrase in ("python", "networking", "linux", "web security", "cybersecurity"):
        if phrase in evidence and skill_in_text(phrase, blob) and phrase.title() not in reasons and phrase not in {item.casefold() for item in reasons}:
            label = phrase.title() if phrase != "web security" else "Web Security"
            if label not in reasons:
                reasons.append(label)
    for line in (profile.projects or "").splitlines():
        title = line.split("|", 1)[0].strip(" -•\t")
        if len(title) >= 4 and title.casefold() in blob.casefold() and title not in reasons:
            reasons.append(title)
    return reasons[:8]


def requirement_block(job: Job, settings: Settings) -> str | None:
    text = f"{job.title}\n{job.description}"
    if mentions_fee(text):
        return "Payment required"
    if _VIDEO.search(text) and settings.avoid_video:
        return "Mandatory video requirement"
    if settings.require_disclosed_pay and compensation_label(job) == "unknown":
        return "Compensation was not disclosed"
    level = (settings.employment or "any").casefold()
    blob = f"{job.title} {job.employment} {job.description[:400]}".casefold()
    if level == "intern" and not re.search(r"intern|trainee", blob):
        return "Not an internship"
    if level == "full-time" and re.search(r"\bintern", blob) and "full-time" not in blob and "full time" not in blob:
        return "Not a full-time role"
    if settings.experience_level == "intern" and not re.search(r"intern|trainee", blob):
        return "Not an internship"
    if level == "part-time" and "part-time" not in blob and "part time" not in blob:
        return "Not a part-time role"
    if level == "contract" and "contract" not in blob:
        return "Not a contract role"
    if settings.avoid_relocation and re.search(r"relocation is required|must relocate|willing to relocate is required", text, re.I):
        return "Relocation required"
    if settings.avoid_sales and re.search(r"\bsales\b", job.title or "", re.I):
        return "Sales role"
    if settings.avoid_above_level and settings.experience_level in {"intern", "junior"}:
        asked = re.search(r"\b(\d+)\+?\s+years?\b", text, re.I)
        if asked and int(asked.group(1)) >= 2:
            return "Experience requirement is above your level"
    return None


def compensation_text(job: Job) -> str:
    label = compensation_label(job)
    if label == "unpaid":
        return "Unpaid"
    if label == "unknown":
        return "Compensation not disclosed"
    amount = monthly_pay(job)
    if amount is None:
        return job.salary_text or "Compensation not disclosed"
    currency = job.salary_currency or ""
    rendered = f"{amount:g}"
    if currency == "INR":
        return f"₹{rendered}/month"
    if currency:
        return f"{currency} {rendered}/month"
    return f"{rendered}/month"


def posted_text(job: Job, now: datetime | None = None) -> str:
    if job.posted_at is None:
        return ""
    moment = now or datetime.now(timezone.utc)
    posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
    days = (moment.date() - posted.astimezone(timezone.utc).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 60:
        return f"{days} days ago"
    return posted.date().isoformat()


def _opportunity_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


def job_facts(job: Job) -> dict:
    text = job.description or ""
    required: list[str] = []
    preferred: list[str] = []
    responsibilities: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" -\t*")
        if not line:
            continue
        folded = line.casefold()
        if folded.startswith("responsib") or raw_line.strip().startswith(("-", "•", "*")):
            if len(line) > 12 and "responsib" not in folded:
                responsibilities.append(line[:180])
        if "prefer" in folded and len(line) < 180:
            preferred.append(line[:180])
        elif re.search(r"\brequired\b|\bmust have\b", folded) and len(line) < 180:
            required.append(line[:180])
    if not required:
        required = list(job.skills[:8])
    experience = ""
    match = re.search(r".{0,40}\b(?:\d+\+?\s+years?|experience).{0,80}", text, re.I)
    if match:
        experience = re.sub(r"\s+", " ", match.group(0)).strip()[:160]
    deadline = ""
    if job.deadline is not None:
        deadline = job.deadline.date().isoformat()
    return {
        "required_skills": required[:6],
        "preferred_skills": preferred[:4],
        "responsibilities": responsibilities[:5],
        "experience": experience,
        "deadline": deadline,
        "employment": job.employment or "",
    }


def _card(job: Job, score: int, profile: Profile, status: str, fit_note: str = "") -> dict:
    direct = safe_http_url(job.official_application_url or job.apply_url or job.url)
    verified = bool(job.official_application_verified and safe_http_url(job.official_application_url or ""))
    facts = job_facts(job)
    return {
        "id": _opportunity_id(direct or job.url),
        "company": job.company,
        "role": job.title,
        "match_score": score,
        "sources": job.sources,
        "location": job.location,
        "work_mode": infer_workplace(job),
        "compensation": compensation_text(job),
        "posted": posted_text(job),
        "availability": status,
        "why": why_matches(job, profile),
        "gaps": potential_gaps(job, profile),
        "required_skills": facts["required_skills"],
        "preferred_skills": facts["preferred_skills"],
        "responsibilities": facts["responsibilities"],
        "experience": facts["experience"],
        "deadline": facts["deadline"],
        "employment": facts["employment"],
        "application": "Supported" if direct else "No application link",
        "official_url": direct if verified else "",
        "official_verified": verified,
        "apply_url": direct,
        "apply_label": "Apply on official site" if verified else "Apply",
        "fit_note": fit_note,
        "url": direct,
        "source_url": safe_http_url(job.url),
        "description": (job.description or "")[:4000],
        "source": job.source,
    }


def analyze_job_market(profile: Profile, settings: Settings, target_count: int | None = None, search=None, fetcher=None, verify_limit: int = 15, progress=None) -> dict:
    """Search widely, then return the best currently usable opportunities."""
    def step(message: str) -> None:
        if progress:
            progress(message)

    target = target_count if target_count is not None else settings.opportunity_count
    target = min(100, max(1, int(target or 20)))
    queries = search_queries(settings)[:8]
    step("Searching job sources...")
    found = (search or search_all_sources)(settings, queries)
    if len(found) == 2:
        jobs, warnings = found
        report: list[dict] = []
    else:
        jobs, warnings, report = found
    raw_count = len(jobs)
    step(f"Analyzing {raw_count} opportunities...")
    normalized = [normalize_listing(job) for job in jobs]
    expired = 0
    usable = []
    for job in normalized:
        state = availability(job)
        job.availability_status = state
        if state == "EXPIRED":
            expired += 1
            continue
        usable.append(job)
    merged, duplicates = merge_duplicates(usable)
    step("Removing duplicates...")
    step("Comparing with your resume...")
    rejected: dict[str, int] = {}
    ranked = []
    nearest: list[tuple[int, Job, str]] = []
    for job in merged:
        decision = screen(job, settings, profile, lambda _job: False)
        if not decision.accept:
            rejected[decision.reason or "Rejected"] = rejected.get(decision.reason or "Rejected", 0) + 1
            close = decision.reason in {"Match score below your minimum", "Pay is below your minimum"}
            intern_search = (settings.employment or "any").casefold() == "intern"
            title_kind = f"{job.title} {job.employment}"
            kind_ok = (not intern_search) or re.search(r"intern|trainee", title_kind, re.I) is not None
            if (
                close
                and kind_ok
                and sector_matches(job, settings.sectors)
                and sector_in_title(job, settings.sectors)
                and not workplace_problem(job, settings)
                and requirement_block(job, settings) is None
            ):
                note = "Below your match score" if (decision.reason or "").startswith("Match") else "Below your minimum stipend"
                nearest.append((decision.score or score_job(job, profile, settings), job, note))
            continue
        blocked = requirement_block(job, settings)
        if blocked:
            rejected[blocked] = rejected.get(blocked, 0) + 1
            continue
        score = decision.score or score_job(job, profile, settings)
        ranked.append((score, job))
    step("Ranking your best matches...")
    ranked.sort(key=lambda item: (item[0], item[1].posted_at.timestamp() if item[1].posted_at else 0), reverse=True)
    pool = ranked[: max(target, verify_limit)]
    active = 0
    checked = 0
    verified = []
    for score, job in pool:
        if checked < verify_limit and fetcher is not False:
            job.availability_status = verify_page(job, fetcher if fetcher is not None else polite_fetcher)
            checked += 1
        else:
            job.availability_status = availability(job)
        if job.availability_status == "EXPIRED":
            expired += 1
            continue
        if job.availability_status == "ACTIVE":
            active += 1
        verified.append((score, job))
    verified.sort(key=lambda item: (item[1].availability_status == "ACTIVE", item[0]), reverse=True)
    top = verified[:target]
    relaxed = False
    if not top and nearest:
        nearest.sort(key=lambda item: item[0], reverse=True)
        relaxed = True
        top = [(score, job) for score, job, _note in nearest[:target]]
        notes = {id(job): note for _score, job, note in nearest}
    else:
        notes = {}
    cards = [
        _card(job, score, profile, job.availability_status, notes.get(id(job), ""))
        for score, job in top
        if safe_http_url(job.apply_url or job.url)
    ]
    visible_report = [row for row in report if row.get("status") != "meta"]
    return {
        "opportunities": cards,
        "source_report": visible_report,
        "warnings": warnings,
        "found": raw_count,
        "analyzed": len(merged),
        "active": active,
        "duplicates": duplicates,
        "expired": expired,
        "rejected": sum(rejected.values()),
        "rejection_counts": rejected,
        "qualified": len(ranked),
        "final_count": len(cards),
        "relaxed": relaxed,
        "discovered": next((row.get("count") or 0 for row in report if row.get("name") == "_discovered"), raw_count),
    }
