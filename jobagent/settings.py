"""Search rules. The agent does not loosen these after you save them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.textutil import split_csv

WORKPLACES = ("any", "remote", "onsite", "hybrid")


@dataclass
class Settings:
    sectors: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    location: str = ""
    workplace: str = "any"
    minimum_stipend: float = 0
    preferred_companies: list[str] = field(default_factory=list)
    excluded_companies: list[str] = field(default_factory=list)
    minimum_score: int = 70
    allow_hybrid: bool = False
    manual_review: bool = False

    def to_dict(self) -> dict:
        return {
            "sectors": self.sectors,
            "roles": self.roles,
            "required_skills": self.required_skills,
            "location": self.location,
            "workplace": self.workplace,
            "minimum_stipend": self.minimum_stipend,
            "preferred_companies": self.preferred_companies,
            "excluded_companies": self.excluded_companies,
            "minimum_score": self.minimum_score,
            "allow_hybrid": self.allow_hybrid,
            "manual_review": self.manual_review,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        workplace = str(data.get("workplace") or "any")
        if workplace not in WORKPLACES:
            workplace = "any"
        try:
            stipend = float(data.get("minimum_stipend") or 0)
        except (TypeError, ValueError):
            stipend = 0
        try:
            score = int(data.get("minimum_score") if data.get("minimum_score") is not None else 70)
        except (TypeError, ValueError):
            score = 70
        return cls(
            sectors=_list(data.get("sectors")),
            roles=_list(data.get("roles")),
            required_skills=_list(data.get("required_skills")),
            location=str(data.get("location") or ""),
            workplace=workplace,
            minimum_stipend=max(0, stipend),
            preferred_companies=_list(data.get("preferred_companies")),
            excluded_companies=_list(data.get("excluded_companies")),
            minimum_score=min(100, max(0, score)),
            allow_hybrid=bool(data.get("allow_hybrid")),
            manual_review=bool(data.get("manual_review")),
        )


def _list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return split_csv(value)
    return []


def settings_path(home: Path) -> Path:
    return home / "settings.json"


def load_settings(home: Path) -> Settings:
    path = settings_path(home)
    with file_lock(path):
        return Settings.from_dict(read_json(path, {}))


def save_settings(home: Path, settings: Settings) -> None:
    path = settings_path(home)
    with file_lock(path):
        atomic_write(path, settings.to_dict())


def _number_error(stipend_raw: str, score_raw: str) -> tuple[float, int] | str:
    try:
        stipend = float(stipend_raw)
    except (TypeError, ValueError):
        return "Minimum stipend must be a number. Use 0 if you only want unpaid roles removed."
    if stipend < 0:
        return "Minimum stipend cannot be negative."
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        return "Minimum match score must be a whole number from 0 to 100."
    if not 0 <= score <= 100:
        return "Minimum match score must be from 0 to 100."
    return stipend, score


def apply_main_fields(settings: Settings, form) -> str | None:
    sector = (form.get("sector") or "").strip()
    roles = (form.get("roles") or "").strip()
    if not sector:
        return "Enter a target sector."
    if not roles:
        return "Enter at least one target role."
    parsed = _number_error(form.get("minimum_stipend") or "", form.get("minimum_score") or "")
    if isinstance(parsed, str):
        return parsed
    stipend, score = parsed
    settings.sectors = split_csv(sector)
    settings.roles = split_csv(roles)
    settings.minimum_stipend = stipend
    settings.minimum_score = score
    return None


def apply_settings_form(form) -> tuple[Settings, str | None]:
    sector = (form.get("sector") or "").strip()
    roles = (form.get("roles") or "").strip()
    if not sector:
        return Settings(), "Enter a target sector."
    if not roles:
        return Settings(), "Enter at least one target role."
    parsed = _number_error(form.get("minimum_stipend") or "", form.get("minimum_score") or "")
    if isinstance(parsed, str):
        return Settings(), parsed
    stipend, score = parsed
    workplace = (form.get("workplace") or "any").strip()
    if workplace not in WORKPLACES:
        return Settings(), "Choose Any, Remote, Onsite, or Hybrid."
    settings = Settings(
        sectors=split_csv(sector),
        roles=split_csv(roles),
        required_skills=split_csv(form.get("required_skills") or ""),
        location=(form.get("location") or "").strip(),
        workplace=workplace,
        minimum_stipend=stipend,
        preferred_companies=split_csv(form.get("preferred_companies") or ""),
        excluded_companies=split_csv(form.get("excluded_companies") or ""),
        minimum_score=score,
        allow_hybrid=(form.get("allow_hybrid") or "") in {"1", "on", "true", "yes"},
        manual_review=(form.get("manual_review") or "") in {"1", "on", "true", "yes"},
    )
    return settings, None
