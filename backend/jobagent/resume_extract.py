"""Read only what a resume explicitly contains. Missing fields stay blank."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)\d{3}[\s-]?\d{4}")
_HEADERS = {
    "skills": "skills",
    "technical skills": "skills",
    "programming languages": "languages",
    "languages": "languages",
    "frameworks": "frameworks",
    "tools": "tools",
    "education": "education",
    "projects": "projects",
    "experience": "experience",
    "work experience": "experience",
    "internships": "experience",
    "certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
}


def _section_targets(line: str) -> list[str] | None:
    if len(line) > 48:
        return None
    normalized = re.sub(r"[^a-z]+", " ", line.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or len(normalized.split()) > 6:
        return None
    if normalized in _HEADERS:
        return [_HEADERS[normalized]]
    if normalized in {"declaration", "references"}:
        return []
    targets = []
    if "certification" in normalized or normalized == "certificates":
        targets.append("certifications")
    if "achievement" in normalized:
        targets.append("achievements")
    return targets or None


def _sections(text: str) -> dict[str, str]:
    current = ["header"]
    buckets: dict[str, list[str]] = {"header": []}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        targets = _section_targets(line)
        if targets is not None:
            current = targets
            for name in current:
                buckets.setdefault(name, [])
            continue
        for name in current:
            buckets.setdefault(name, []).append(line)
    return {name: "\n".join(lines) for name, lines in buckets.items()}


def _split_items(text: str) -> list[str]:
    parts = re.split(r"[,•|/]|\n| - ", text or "")
    found = []
    for part in parts:
        item = re.sub(r"\s+", " ", part).strip(" .-")
        if 1 < len(item) <= 40 and item not in found:
            found.append(item)
    return found[:24]


def _name(header: str) -> str:
    for line in header.splitlines():
        candidate = re.sub(r"\s+", " ", line).strip()
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}", candidate):
            return candidate
    return ""


def _education_bits(text: str) -> dict[str, str]:
    degree = ""
    match = re.search(r"\b(B\.?\s?Tech|B\.?\s?E\.?|M\.?\s?Tech|B\.?Sc|M\.?Sc|Bachelor(?: of [A-Za-z ]+)?|Master(?: of [A-Za-z ]+)?|Ph\.?D)\b", text, re.I)
    if match:
        degree = re.sub(r"\s+", " ", match.group(0)).strip()
    branch = ""
    branch_match = re.search(r"\b(Computer Science|CSE|Information Technology|Electronics|Cybersecurity|Data Science)\b", text, re.I)
    if branch_match:
        branch = branch_match.group(0)
    college = ""
    for line in text.splitlines():
        if re.search(r"\b(university|college|institute|iit|nit)\b", line, re.I):
            college = line.strip()[:120]
            break
    full_years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    graduation = full_years[-1] if full_years else ""
    return {"degree": degree, "branch": branch, "college": college, "graduation_year": graduation}


def extract_resume(text: str) -> dict:
    sections = _sections(text or "")
    header = sections.get("header", "")
    skills = _split_items(sections.get("skills", ""))
    education = _education_bits(sections.get("education", "") or header)
    email = _EMAIL.search(text or "")
    phone = _PHONE.search(text or "")
    return {
        "full_name": _name(header),
        "email": email.group(0) if email else "",
        "phone": phone.group(0) if phone else "",
        "skills": skills,
        "languages": ", ".join(_split_items(sections.get("languages", ""))),
        "frameworks": ", ".join(_split_items(sections.get("frameworks", ""))),
        "tools": ", ".join(_split_items(sections.get("tools", ""))),
        "education_raw": sections.get("education", ""),
        "experience_raw": sections.get("experience", ""),
        "projects": sections.get("projects", ""),
        "certifications": sections.get("certifications", ""),
        "achievements": sections.get("achievements", ""),
        "degree": education["degree"],
        "branch": education["branch"],
        "college": education["college"],
        "graduation_year": education["graduation_year"],
    }


def apply_extraction(profile, extracted: dict, overwrite: bool = False) -> None:
    """Fill blank profile fields from the resume. Existing text stays unless overwrite is set."""
    for key, value in extracted.items():
        if key == "skills":
            if value and (overwrite or not profile.skills):
                profile.skills = list(value)
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        current = getattr(profile, key, "")
        if overwrite or not str(current).strip():
            setattr(profile, key, value.strip())
