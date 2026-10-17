"""Shared records. Personal data lives only in the local data folder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:
    source: str
    company: str
    title: str
    url: str
    apply_url: str = ""
    location: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category: str = ""
    employment: str = ""
    remote: bool | None = None
    workplace: str = "unknown"
    salary_text: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str = ""
    salary_currency: str = ""
    posted_at: datetime | None = None
    deadline: datetime | None = None

    def __post_init__(self) -> None:
        if not self.apply_url:
            self.apply_url = self.url
        self.description = (self.description or "")[:15000]
        self.tags = [str(tag).strip() for tag in self.tags if str(tag).strip()][:40]


@dataclass
class Secrets:
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    api_model: str = "gpt-4o-mini"


@dataclass
class ApplyResult:
    status: str
    result: str = ""
    reason: str = ""
    blocks_retry: bool = False
    submit_clicked: bool = False
    screenshot: str = ""
    filled: list[str] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    needs_input: list[str] = field(default_factory=list)
