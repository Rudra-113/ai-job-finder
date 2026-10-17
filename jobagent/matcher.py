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
            profile.certifications,
            profile.achievements,
            profile.languages,
            profile.frameworks,
            profile.tools,
            profile.domains,
            profile.degree,
            profile.branch,
            profile.college,
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


_GENERIC = {"intern", "internship", "trainee", "remote", "india", "engineer", "engineering"}
_EXPAND = {
    "cybersecurity": {"security", "cyber"},
    "cyber": {"security", "cybersecurity"},
    "infosec": {"security", "cybersecurity"},
    "vapt": {"security", "penetration", "vulnerability"},
    "pentest": {"security", "penetration", "vulnerability"},
    "penetration": {"security", "vulnerability", "vapt"},
    "soc": {"security", "analyst"},
    "appsec": {"security", "application"},
}


def _expanded(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9+#.]+", (text or "").casefold()))
    extra: set[str] = set()
    for token in tokens:
        extra.update(_EXPAND.get(token, ()))
    return tokens | extra


def semantic_role_points(job: Job, roles: list[str]) -> int:
    """Related titles count. 'Security Engineering Intern' can match 'Cybersecurity Intern'."""
    title = _expanded(job.title)
    hay = _expanded(f"{job.title} {job.employment} {job.category} {' '.join(job.tags)} {job.description[:2000]}")
    best = 0
    for role in roles:
        wanted = {token for token in _expanded(role) if token not in _GENERIC and len(token) > 2}
        if not wanted:
            wanted = _expanded(role)
        if not wanted:
            continue
        if wanted & title:
            best = max(best, 30)
        elif len(wanted & hay) / len(wanted) >= 0.34:
            best = max(best, 18)
    return best


def years_experience(profile: Profile) -> float | None:
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", f"{profile.experience_raw}\n{profile.cv_text[:2500]}")]
    if len(years) < 2:
        return None
    return float(min(40, max(years) - min(years)))


def _weights(settings: Settings) -> dict[str, int]:
    from jobagent.settings import normalize_weights

    return normalize_weights(getattr(settings, "match_weights", None))


def score_parts(job: Job, profile: Profile, settings: Settings) -> dict[str, int]:
    """Weighted parts. Each value is between 0 and that part's weight."""
    weights = _weights(settings)
    blob = listing_blob(job)
    evidence = evidence_text(profile)
    wanted = [skill for skill in profile.skills if skill]
    for skill in settings.preferred_skills:
        if skill_in_text(skill, evidence) and skill not in wanted:
            wanted.append(skill)
    if wanted:
        hits = sum(1 for skill in wanted if skill_in_text(skill, blob))
        skill_points = round(weights["skill"] * hits / len(wanted))
    else:
        overlap = distinctive(evidence) & distinctive(blob)
        skill_points = min(weights["skill"], len(overlap) * 3)
    role_raw = max(
        30 if role_in_title(job, settings.roles) else 18 if role_matches(job, settings.roles) else 0,
        semantic_role_points(job, settings.roles),
    )
    role_points = round(weights["role"] * min(role_raw, 30) / 30)
    overlap = distinctive(evidence) & distinctive(job.description or "")
    asked = re.search(r"\b(\d+)\+?\s+years?\b", job.description or "", re.I)
    have = years_experience(profile)
    if asked and have is not None and have < int(asked.group(1)):
        experience_points = round(weights["experience"] * 0.2)
    elif len(overlap) >= 2:
        experience_points = weights["experience"]
    elif "intern" in evidence.casefold() and re.search(r"intern|trainee", f"{job.title} {job.description[:300]}", re.I):
        experience_points = round(weights["experience"] * 0.35)
    else:
        experience_points = 0
    needed = required_degree(job.description)
    have_degree = education_level(profile)
    if needed is None or _RANKS[have_degree] >= _RANKS[needed]:
        education_points = weights["education"]
    else:
        education_points = 0
    from jobagent.criteria import infer_workplace

    place = infer_workplace(job)
    preference = (settings.workplace or "any").casefold()
    if preference in {"", "any"} or place == preference or (preference == "remote" and place == "unknown"):
        location_points = weights["location"]
    elif settings.allow_hybrid and place == "hybrid":
        location_points = weights["location"]
    else:
        location_points = 0
    label_pay = job.salary_min or job.salary_text
    if re.search(r"\bunpaid\b", f"{job.title}\n{job.description[:500]}", re.I):
        compensation_points = 0
    elif label_pay:
        compensation_points = weights["compensation"]
    else:
        compensation_points = round(weights["compensation"] * 0.6)
    preference_points = weights["preference"] if company_named(job.company, settings.preferred_companies) else 0
    return {
        "skill": skill_points,
        "role": role_points,
        "experience": experience_points,
        "education": education_points,
        "location": location_points,
        "compensation": compensation_points,
        "preference": preference_points,
    }


def score_job(job: Job, profile: Profile, settings: Settings) -> int:
    parts = score_parts(job, profile, settings)
    evidence = evidence_text(profile)
    penalties = 0
    if required_degree(job.description) and _RANKS[education_level(profile)] < _RANKS[required_degree(job.description) or "none"]:
        penalties += 25
    if re.search(r"portfolio (?:is )?required", job.description or "", re.I) and not profile.portfolio:
        penalties += 15
    for skill in settings.required_skills:
        if not skill_in_text(skill, evidence):
            penalties += 35
    return max(0, min(100, sum(parts.values()) - penalties))


_GAP_WORDS = (
    "siem", "splunk", "qradar", "aws", "azure", "kubernetes", "docker", "burp", "wireshark",
    "linux", "python", "java", "react", "sql", "terraform", "ansible", "active directory",
    "penetration testing", "oscp", "cissp", "ceh", "soc", "ids", "ips",
)


def potential_gaps(job: Job, profile: Profile) -> list[str]:
    """Skills the listing asks for that are absent from the saved profile."""
    evidence = evidence_text(profile)
    text = f"{job.title}\n{job.description}\n{' '.join(job.skills)}\n{' '.join(job.tags)}"
    gaps = []
    asked = re.search(r"\b(\d+)\+?\s+years?\b", job.description or "", re.I)
    have = years_experience(profile)
    if asked and have is not None and have < int(asked.group(1)):
        gaps.append(f"{asked.group(1)} years experience preferred")
    for word in _GAP_WORDS:
        if not skill_in_text(word, text) or skill_in_text(word, evidence):
            continue
        window = text.casefold()
        if not re.search(r"prefer|required|experience|must|familiar", window):
            continue
        label = word.upper() if len(word) <= 4 else word.title()
        phrase = f"{label} experience preferred"
        if phrase not in gaps:
            gaps.append(phrase)
        if len(gaps) >= 5:
            break
    return gaps[:5]
