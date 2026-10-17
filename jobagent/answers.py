"""Answers that stay inside the saved profile. Missing facts stop the application."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

import httpx

from jobagent.models import Job, Secrets
from jobagent.profile import Profile, parse_experience
from jobagent.textutil import skill_in_text

GLUE = {
    "the", "and", "or", "to", "for", "of", "in", "on", "with", "at", "by", "from",
    "as", "is", "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "i", "my", "me", "we", "our", "you", "your", "it", "its", "if", "so",
    "not", "no", "yes", "have", "has", "had", "do", "did", "using", "use", "used",
    "during", "while", "where", "when", "which", "who", "whom", "what", "how",
    "also", "including", "include", "across", "into", "over", "under", "than",
    "then", "can", "will", "would", "could", "should", "may", "might", "about",
    "after", "before", "between", "through", "such", "other", "another", "same",
    "per", "via", "within", "without", "none", "a", "an",
}

_EEO = re.compile(r"\b(gender|race|ethnic|hispanic|latino|veteran|disability|pronouns?)\b", re.I)
_ACCOMMODATION = re.compile(r"accommodat|adjustment|disability support", re.I)


@dataclass
class Answer:
    action: str
    value: str = ""
    reason: str = ""


def is_eeo(label: str) -> bool:
    if _ACCOMMODATION.search(label or ""):
        return False
    return bool(_EEO.search(label or ""))


def profile_corpus(profile: Profile) -> str:
    lines = [
        profile.full_name,
        profile.email,
        profile.phone,
        profile.city,
        profile.country,
        profile.portfolio,
        profile.linkedin,
        profile.github,
        ", ".join(profile.skills),
        profile.education_raw,
        profile.experience_raw,
        profile.projects,
        profile.extra_facts,
        profile.cv_text,
    ]
    if profile.work_authorized in {"yes", "no"}:
        lines.append(f"Work authorized: {profile.work_authorized}")
    if profile.needs_sponsorship in {"yes", "no"}:
        lines.append(f"Needs sponsorship: {profile.needs_sponsorship}")
    return "\n".join(line for line in lines if line and str(line).strip())


def grounded(answer: str, citations: list, corpus: str) -> bool:
    if not answer or not isinstance(citations, list) or not citations:
        return False
    if re.search(r"as an ai|language model", answer, re.I):
        return False
    corpus_cf = corpus.casefold()
    for citation in citations:
        if not isinstance(citation, str) or len(citation.strip()) < 2:
            return False
        if citation.strip().casefold() not in corpus_cf:
            return False
    if any(number not in corpus for number in re.findall(r"\d+", answer)):
        return False
    for token in re.findall(r"[A-Za-z][A-Za-z+.#]{2,}", answer):
        word = token.casefold().strip(".#+")
        if not word or word in GLUE:
            continue
        if word not in corpus_cf:
            return False
    return True


def _parse_month(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.casefold() in {"present", "current", "now", "ongoing"}:
        return date.today()
    match = re.match(r"^(\d{4})(?:-(\d{2}))?$", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    if not 1 <= month <= 12:
        return None
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def years_for(profile: Profile, skill: str | None) -> str | None:
    entries = parse_experience(profile.experience_raw)
    if skill:
        entries = [
            entry
            for entry in entries
            if skill_in_text(skill, f"{entry.title} {entry.details} {entry.company}")
        ]
        if not entries:
            return None
    starts: list[date] = []
    ends: list[date] = []
    for entry in entries:
        start = _parse_month(entry.start)
        end = _parse_month(entry.end) or date.today()
        if start and end and end >= start:
            starts.append(start)
            ends.append(end)
    if not starts:
        return None
    start, end = min(starts), max(ends)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months < 12:
        return "less than 1"
    return str(months // 12)


def fact_lookup(question: str, facts: str) -> str | None:
    folded = question.casefold()
    for line in (facts or "").splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label, value = label.strip(), value.strip()
        if len(label) >= 4 and value and label.casefold() in folded:
            return value
    return None


def factual_motivation(profile: Profile) -> str | None:
    sentences: list[str] = []
    bits = [f"{entry.title} at {entry.company}" for entry in parse_experience(profile.experience_raw) if entry.title and entry.company]
    if bits:
        sentences.append("Experience: " + "; ".join(bits) + ".")
    if profile.skills:
        sentences.append("Skills: " + ", ".join(profile.skills) + ".")
    if profile.projects.strip():
        sentences.append(profile.projects.strip())
    if profile.portfolio:
        sentences.append("Portfolio: " + profile.portfolio)
    if not sentences:
        return None
    return " ".join(sentences)


def _fill(value: str) -> Answer:
    return Answer("fill", value.strip())


def _stop(reason: str) -> Answer:
    return Answer("stop", reason=reason)


def _skip() -> Answer:
    return Answer("skip")


def _missing(required: bool, reason: str) -> Answer:
    return _stop(reason) if required else _skip()


def answer_question(question: str, required: bool, profile: Profile, job: Job, secrets: Secrets, client: httpx.Client | None = None) -> Answer:
    text = re.sub(r"\s+", " ", question or "").strip()
    folded = text.casefold()
    if not text:
        return _missing(required, "A required question had no label, so it was left blank.")
    fact = fact_lookup(text, profile.extra_facts)
    if fact:
        return _fill(fact)
    if re.search(r"salary|compensation|stipend expectation|desired pay|pay expectation", folded):
        return _missing(
            required,
            "Desired pay is not in your Profile. Add a fact such as 'Desired pay: 4000 per month', or leave this application paused.",
        )
    if re.search(r"authori[sz]ed", folded) and re.search(r"sponsor", folded):
        if profile.work_authorized == "yes" and profile.needs_sponsorship == "no":
            return _fill("Yes")
        if profile.work_authorized == "no" or profile.needs_sponsorship == "yes":
            return _fill("No")
        return _missing(required, "Set work authorization and sponsorship on your Profile before this question can be answered.")
    if re.search(r"sponsor", folded):
        if profile.needs_sponsorship == "yes":
            return _fill("Yes")
        if profile.needs_sponsorship == "no":
            return _fill("No")
        return _missing(required, "Set sponsorship on your Profile. It was not guessed.")
    if re.search(r"authori[sz]ed to work|legally authori|eligible to work|right to work", folded):
        if profile.work_authorized == "yes":
            return _fill("Yes")
        if profile.work_authorized == "no":
            return _fill("No")
        return _missing(required, "Set work authorization on your Profile. It was not guessed.")
    if re.search(r"previously worked|worked at|consulted for|worked for", folded):
        company = job.company.casefold()
        evidence = profile_corpus(profile).casefold()
        if company and company in evidence:
            return _fill("Yes")
        if profile.cv_text.strip() or profile.experience_raw.strip():
            return _fill("No")
        return _missing(required, "Work history is empty, so a previous-employer question was not answered.")
    years = re.search(r"how many years|years of (?:professional |work |relevant )?experience", folded)
    if years:
        skill = None
        for candidate in sorted(profile.skills, key=len, reverse=True):
            if skill_in_text(candidate, text):
                skill = candidate
                break
        if skill is None:
            skill_match = re.search(r"experience (?:with|in|using) ([A-Za-z0-9+#.]+)", text, re.I)
            skill = skill_match.group(1) if skill_match else None
            if re.search(r"how many years of experience do you have\??$", folded) or re.search(
                r"years of (?:professional |work )?experience\??$", folded
            ):
                skill = None
        amount = years_for(profile, skill)
        if amount:
            return _fill(amount)
        return _missing(required, "Years of experience could not be calculated from the dates on your Profile.")
    if re.search(r"\bproject\b", folded):
        if profile.projects.strip():
            return _fill(profile.projects.strip())
        return _missing(required, "Add a project on your Profile. One was not invented.")
    if re.search(r"cover letter|why (?:do you|are you)|tell us about yourself|about you", folded):
        motivation = factual_motivation(profile)
        if motivation:
            return _fill(motivation)
        return _missing(required, "There is not enough saved experience to answer that without guessing.")
    if re.search(r"accommodat|adjustment", folded):
        return _missing(required, "Add an accommodation fact on your Profile, or leave this application paused. Nothing was invented.")
    if not required:
        return _skip()
    if not secrets.api_key:
        return _stop(
            "This required question is not answered by your saved facts. "
            "Add a Profile fact, or add an API key. Nothing was invented. Question: " + text[:140]
        )
    return llm_answer(text, profile, secrets, client)


def llm_answer(question: str, profile: Profile, secrets: Secrets, client: httpx.Client | None = None) -> Answer:
    corpus = profile_corpus(profile)
    payload = {
        "model": secrets.api_model or "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You answer one job-application question using only the candidate facts. "
                    'Return JSON: {"answer": string or null, "citations": [exact substrings copied from the facts]}. '
                    "If the facts do not contain the answer, set answer to null and citations to an empty list. "
                    "Do not invent employers, dates, skills, degrees, or numbers. "
                    "Do not treat a job description as the candidate's experience."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question[:2000]}\n\nCandidate facts:\n{corpus[:12000]}",
            },
        ],
    }
    own_client = client is None
    client = client or httpx.Client()
    try:
        response = client.post(
            secrets.api_base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {secrets.api_key}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception:
        return _stop("The answer service could not be reached. This application was stopped.")
    finally:
        if own_client:
            client.close()
    parsed = _extract_json(content)
    if not parsed:
        return _stop("The answer service returned nothing usable. This application was stopped.")
    answer = parsed.get("answer")
    citations = parsed.get("citations") or []
    if not isinstance(answer, str) or not answer.strip() or not grounded(answer, citations, corpus):
        return _stop("Could not answer from your CV without guessing: " + question[:140])
    return _fill(answer.strip()[:1500])


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def match_option(value: str, options: list[dict]) -> str | None:
    wanted = (value or "").strip().casefold()
    if not wanted:
        return None
    labels = []
    for option in options:
        label = option.get("label") if isinstance(option, dict) else str(option)
        if label and label.strip() and label.strip().casefold() not in {"select", "select...", "choose"}:
            labels.append(label.strip())
    for label in labels:
        if label.casefold() == wanted:
            return label
    if wanted in {"yes", "no"}:
        return None
    if len(wanted) >= 4:
        for label in labels:
            if wanted in label.casefold():
                return label
    return None
