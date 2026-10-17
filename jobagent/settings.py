"""Search rules. The agent does not loosen these after you save them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jobagent.paths import atomic_write, file_lock, read_json
from jobagent.textutil import split_csv

WORKPLACES = ("any", "remote", "onsite", "hybrid")
EMPLOYMENT = ("any", "intern", "full-time", "part-time", "contract")
EXPERIENCE = ("any", "intern", "junior")
DEFAULT_WEIGHTS = {
    "skill": 30,
    "role": 20,
    "experience": 15,
    "education": 10,
    "location": 10,
    "compensation": 5,
    "preference": 10,
}


@dataclass
class Settings:
    sectors: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    location: str = ""
    workplace: str = "any"
    minimum_stipend: float = 0
    minimum_salary: float = 0
    preferred_companies: list[str] = field(default_factory=list)
    excluded_companies: list[str] = field(default_factory=list)
    minimum_score: int = 70
    allow_hybrid: bool = False
    manual_review: bool = False
    opportunity_count: int = 20
    employment: str = "any"
    experience_level: str = "any"
    avoid_video: bool = False
    avoid_unpaid: bool = True
    avoid_relocation: bool = False
    avoid_sales: bool = False
    avoid_above_level: bool = False
    require_disclosed_pay: bool = False
    max_posting_age: int = 0
    match_weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def to_dict(self) -> dict:
        return {
            "sectors": self.sectors,
            "roles": self.roles,
            "required_skills": self.required_skills,
            "preferred_skills": self.preferred_skills,
            "location": self.location,
            "workplace": self.workplace,
            "minimum_stipend": self.minimum_stipend,
            "minimum_salary": self.minimum_salary,
            "preferred_companies": self.preferred_companies,
            "excluded_companies": self.excluded_companies,
            "minimum_score": self.minimum_score,
            "allow_hybrid": self.allow_hybrid,
            "manual_review": self.manual_review,
            "opportunity_count": self.opportunity_count,
            "employment": self.employment,
            "experience_level": self.experience_level,
            "avoid_video": self.avoid_video,
            "avoid_unpaid": self.avoid_unpaid,
            "avoid_relocation": self.avoid_relocation,
            "avoid_sales": self.avoid_sales,
            "avoid_above_level": self.avoid_above_level,
            "require_disclosed_pay": self.require_disclosed_pay,
            "max_posting_age": self.max_posting_age,
            "match_weights": self.match_weights,
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
            preferred_skills=_list(data.get("preferred_skills")),
            location=str(data.get("location") or ""),
            workplace=workplace,
            minimum_stipend=max(0, stipend),
            minimum_salary=max(0, _float(data.get("minimum_salary"))),
            preferred_companies=_list(data.get("preferred_companies")),
            excluded_companies=_list(data.get("excluded_companies")),
            minimum_score=min(100, max(0, score)),
            allow_hybrid=bool(data.get("allow_hybrid")),
            manual_review=bool(data.get("manual_review")),
            opportunity_count=_count(data.get("opportunity_count")),
            employment=_choice(data.get("employment"), EMPLOYMENT, "any"),
            experience_level=_choice(data.get("experience_level"), EXPERIENCE, "any"),
            avoid_video=bool(data.get("avoid_video")),
            avoid_unpaid=True if "avoid_unpaid" not in data else bool(data.get("avoid_unpaid")),
            avoid_relocation=bool(data.get("avoid_relocation")),
            avoid_sales=bool(data.get("avoid_sales")),
            avoid_above_level=bool(data.get("avoid_above_level")),
            require_disclosed_pay=bool(data.get("require_disclosed_pay")),
            max_posting_age=_age(data.get("max_posting_age")),
            match_weights=normalize_weights(data.get("match_weights")),
        )


def normalize_weights(value) -> dict:
    base = dict(DEFAULT_WEIGHTS)
    if isinstance(value, dict):
        for key in base:
            if key not in value or value[key] in (None, ""):
                continue
            try:
                base[key] = min(100, max(0, int(value[key])))
            except (TypeError, ValueError):
                continue
    total = sum(base.values())
    if total == 100:
        return base
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    scaled = {key: int(round(points * 100 / total)) for key, points in base.items()}
    drift = 100 - sum(scaled.values())
    scaled["skill"] = min(100, max(0, scaled["skill"] + drift))
    return scaled


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _age(value) -> int:
    try:
        return min(365, max(0, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _count(value) -> int:
    try:
        count = int(value if value is not None else 20)
    except (TypeError, ValueError):
        count = 20
    return min(100, max(1, count))


def _choice(value, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or default).strip().casefold()
    return text if text in allowed else default


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


def _form_weights(form) -> dict:
    if (form.get("weight_skill") or "") == "":
        return dict(DEFAULT_WEIGHTS)
    raw = {key: form.get(f"weight_{key}") for key in DEFAULT_WEIGHTS}
    return normalize_weights(raw)


def apply_main_fields(settings: Settings, form) -> str | None:
    sector = (form.get("sector") or "").strip()
    roles = (form.get("roles") or "").strip()
    if sector:
        settings.sectors = split_csv(sector)
    if roles:
        settings.roles = split_csv(roles)
    if (form.get("minimum_stipend") or "").strip() or (form.get("minimum_score") or "").strip():
        parsed = _number_error(form.get("minimum_stipend") or "0", form.get("minimum_score") or str(settings.minimum_score))
        if isinstance(parsed, str):
            return parsed
        stipend, score = parsed
        if (form.get("minimum_stipend") or "").strip():
            settings.minimum_stipend = stipend
        if (form.get("minimum_score") or "").strip():
            settings.minimum_score = score
    if (form.get("opportunity_count") or "").strip():
        settings.opportunity_count = _count(form.get("opportunity_count"))
    from jobagent.intelligence import apply_natural_request

    apply_natural_request(settings, form.get("request") or "")
    if not settings.sectors or not settings.roles:
        return "Add a target sector and role in Settings, or describe them in the search."
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
        opportunity_count=_count(form.get("opportunity_count")),
        employment=_choice(form.get("employment"), EMPLOYMENT, "any"),
        experience_level=_choice(form.get("experience_level"), EXPERIENCE, "any"),
        avoid_video=(form.get("avoid_video") or "") in {"1", "on", "true", "yes"},
        avoid_unpaid=(form.get("avoid_unpaid") or "") in {"1", "on", "true", "yes"},
        avoid_relocation=(form.get("avoid_relocation") or "") in {"1", "on", "true", "yes"},
        avoid_sales=(form.get("avoid_sales") or "") in {"1", "on", "true", "yes"},
        avoid_above_level=(form.get("avoid_above_level") or "") in {"1", "on", "true", "yes"},
        require_disclosed_pay=(form.get("require_disclosed_pay") or "") in {"1", "on", "true", "yes"},
        minimum_salary=_float(form.get("minimum_salary")),
        preferred_skills=split_csv(form.get("preferred_skills") or ""),
        max_posting_age=_age(form.get("max_posting_age")),
        match_weights=_form_weights(form),
    )
    return settings, None
