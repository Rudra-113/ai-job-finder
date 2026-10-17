"""Decide whether a listing is allowed to reach the application step."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from jobagent.criteria import (
    age_problem,
    company_named,
    required_skills_listed,
    role_matches,
    sector_matches,
    stipend_problem,
    workplace_problem,
)
from jobagent.matcher import score_job
from jobagent.models import Job
from jobagent.profile import Profile
from jobagent.safety import mentions_fee
from jobagent.settings import Settings
from jobagent.textutil import safe_http_url


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str = ""
    score: int = 0


def screen(
    job: Job,
    settings: Settings,
    profile: Profile,
    already,
    now: datetime | None = None,
) -> Decision:
    moment = now or datetime.now(timezone.utc)
    if not job.title.strip() or not job.company.strip() or not safe_http_url(job.apply_url or job.url):
        return Decision(False, "Missing a title, company, or link")
    if already(job):
        return Decision(False, "Already processed")
    aged = age_problem(job, moment)
    if aged:
        return Decision(False, aged)
    if mentions_fee(f"{job.title}\n{job.description}"):
        return Decision(False, "Asks for payment or looks unsafe")
    pay = stipend_problem(job, settings.minimum_stipend)
    if pay:
        return Decision(False, pay)
    if company_named(job.company, settings.excluded_companies):
        return Decision(False, "Excluded company")
    if not sector_matches(job, settings.sectors):
        return Decision(False, "Outside your sector")
    if not role_matches(job, settings.roles):
        return Decision(False, "Role does not match")
    if not required_skills_listed(job, settings.required_skills):
        return Decision(False, "Does not list a required skill")
    place = workplace_problem(job, settings)
    if place:
        return Decision(False, place)
    score = score_job(job, profile, settings)
    if score < settings.minimum_score:
        return Decision(False, "Match score below your minimum", score)
    return Decision(True, "", score)
