import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobagent.models import Job
from jobagent.profile import Profile
from jobagent.settings import Settings

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


def write_cv(tmp_path: Path) -> Path:
    path = tmp_path / "cv.txt"
    path.write_text(
        "Ada Lovelace. Python and SQL data analyst intern. Built a Python data dashboard.",
        encoding="utf-8",
    )
    return path


def strong_profile(tmp_path: Path) -> Profile:
    cv = write_cv(tmp_path)
    return Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone="+14155550100",
        city="Berlin",
        country="Germany",
        portfolio="https://example.com/ada",
        work_authorized="yes",
        needs_sponsorship="no",
        skills=["Python", "SQL"],
        education_raw="BSc | Statistics | State University | 2026",
        experience_raw="Data Analyst Intern | City Lab | 2024-06 | 2024-08 | Used Python and SQL",
        projects="Built a Python data dashboard for City Lab.",
        cv_path=str(cv),
        cv_text=cv.read_text(encoding="utf-8"),
    )


def strong_settings(**kwargs) -> Settings:
    data = dict(
        sectors=["data"],
        roles=["data analyst intern"],
        minimum_stipend=1000,
        minimum_score=70,
        workplace="remote",
    )
    data.update(kwargs)
    return Settings(**data)


def strong_job(**kwargs) -> Job:
    data = dict(
        source="remotive",
        company="Northwind",
        title="Data Analyst Intern",
        url="https://jobs.example.com/northwind/data-analyst-intern",
        apply_url="https://jobs.example.com/northwind/data-analyst-intern",
        location="Worldwide",
        description=(
            "Remote data internship using Python and SQL. Bachelor's degree preferred. "
            "Stipend 3000 per month. The work includes a dashboard."
        ),
        tags=["python", "sql", "data"],
        category="Data",
        employment="intern",
        remote=True,
        workplace="remote",
        salary_text="Stipend 3000 per month",
        salary_min=3000,
        salary_period="month",
        posted_at=NOW,
    )
    data.update(kwargs)
    return Job(**data)
