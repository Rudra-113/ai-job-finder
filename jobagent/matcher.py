"""Suitability score from the saved CV, skills, education, and projects.

The score never adds a skill or employer that is absent from the profile.
"""

from __future__ import annotations

import re

from jobagent.criteria import company_named, listing_blob, role_in_title, role_matches
from jobagent.models import Job
from jobagent.profile import Profile
from jobagent.settings import Settings
from jobagent.textutil import distinctive, skill_in_text

_DEGREE = (
    ("phd", re.compile(r"(ph\.?d|doctorate).{0,40}required|required.{0,40}(ph\.?d|doctorate)|must have (a |an )?(ph\.?d|doctorate)", re.I)),
    ("master", re.compile(r"(master'?s|m\.sc\b|msc\b).{0,40}required|required.{0,40}(master'?s|m\.sc\b|msc\b)|must have (a |an )?master", re.I)),
    ("bachelor", re.compile(r"(bachelor'?s|b\.sc\b|bsc\b).{0,40}required|required.{0,40}(bachelor'?s|b\.sc\b|bsc\b)|must have (a |an )?bachelor", re.I)),
)
_RANKS = {"none": 0, "bachelor": 1, "master": 2, "phd": 3}


def evidence_text(profile: Profile) -> str:
    return "\n".join(
        part
        for part in (
            profile.cv_text,
            ", ".join(profile.skills),
            profile.experience_raw,
            profile.projects,
            profile.education_raw,
            profile.extra_facts,
        )
        if part
    )


def education_level(profile: Profile) -> str:
    text = f"{profile.education_raw}\n{profile.cv_text}".casefold()
    if re.search(r"\bph\.?d\b|\bdoctorate\b|\bd\.phil\b", text):
        return "phd"
    if re.search(r"\bmaster\b|\bm\.sc\b|\bmsc\b|\bm\.s\b|\bmba\b|\bm\.eng\b", text):
        return "master"
    if re.search(r"\bbachelor\b|\bb\.sc\b|\bbsc\b|\bb\.s\b|\bb\.a\b|\bba\b|\bb\.eng\b|\bundergraduate\b", text):
        return "bachelor"
    return "none"


def required_degree(text: str) -> str | None:
    for level, pattern in _DEGREE:
        if pattern.search(text or ""):
            return level
    return None


def score_job(job: Job, profile: Profile, settings: Settings) -> int:
    blob = listing_blob(job)
    evidence = evidence_text(profile)
    role_points = 30 if role_in_title(job, settings.roles) else 15 if role_matches(job, settings.roles) else 0
    if profile.skills:
        hits = sum(1 for skill in profile.skills if skill_in_text(skill, blob))
        skill_points = round(40 * hits / len(profile.skills))
    else:
        skill_points = 0
    needed = required_degree(job.description)
    have = education_level(profile)
    penalties = 0
    if needed is None or _RANKS[have] >= _RANKS[needed]:
        education_points = 10
    else:
        education_points = 0
        penalties += 25
    overlap = distinctive(evidence) & distinctive(blob)
    background_points = min(10, 5 * len(overlap))
    preferred_points = 10 if company_named(job.company, settings.preferred_companies) else 0
    portfolio_points = 5 if profile.portfolio and re.search(r"\bportfolio\b", blob, re.I) else 0
    if re.search(r"portfolio (?:is )?required", job.description or "", re.I) and not profile.portfolio:
        penalties += 15
    for skill in settings.required_skills:
        if not skill_in_text(skill, evidence):
            penalties += 25
    total = role_points + skill_points + education_points + background_points + preferred_points + portfolio_points
    return max(0, min(100, total - penalties))
