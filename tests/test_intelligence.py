from jobagent.intelligence import analyze_job_market, apply_natural_request, availability, why_matches
from jobagent.search import fetch_upwork, parse_unstop
from jobagent.settings import Settings
from tests.conftest import NOW, strong_job, strong_profile, strong_settings


def _search(jobs, report=None):
    def search(_settings, _queries=None):
        return jobs, [], report or []

    return search


def test_natural_request_sets_existing_preferences():
    settings = Settings(roles=["analyst"])
    apply_natural_request(
        settings,
        "Find me 20 remote cybersecurity internships in India, minimum ₹10,000 stipend, preferably SOC or security research.",
    )
    assert settings.opportunity_count == 20
    assert settings.workplace == "remote"
    assert settings.location == "India"
    assert settings.minimum_stipend == 10000
    assert settings.employment == "intern"
    assert any("cyber" in sector.casefold() for sector in settings.sectors)
    roles = [role.casefold() for role in settings.roles]
    assert "soc" in roles
    assert "security research" in roles
    assert any("intern" in role for role in roles)


def test_duplicates_keep_one_card_and_the_official_url(tmp_path):
    linkedin = strong_job(
        source="linkedin",
        url="https://www.linkedin.com/jobs/view/100",
        apply_url="https://www.linkedin.com/jobs/view/100",
        sources=["LinkedIn"],
    )
    official = strong_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/northwind/jobs/100",
        apply_url="https://boards.greenhouse.io/northwind/jobs/100",
        sources=["Company Careers"],
    )
    report = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(),
        search=_search([linkedin, official]),
        fetcher=False,
    )
    assert report["duplicates"] == 1
    assert report["final_count"] == 1
    card = report["opportunities"][0]
    assert "LinkedIn" in card["sources"]
    assert "Company Careers" in card["sources"]
    assert card["official_verified"] is True
    assert "greenhouse.io" in card["official_url"]


def test_closed_listing_is_not_returned(tmp_path):
    closed = strong_job(description="This position has been filled. Remote data internship using Python and SQL. Stipend 3000 per month.")
    report = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(),
        search=_search([closed]),
        fetcher=False,
    )
    assert report["final_count"] == 0
    assert report["expired"] >= 1


def test_target_count_is_the_final_list_not_the_search_limit(tmp_path):
    jobs = [
        strong_job(company=f"Co{index}", url=f"https://jobs.example.com/n{index}", apply_url=f"https://jobs.example.com/n{index}")
        for index in range(6)
    ]
    report = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(opportunity_count=2),
        search=_search(jobs),
        fetcher=False,
    )
    assert report["found"] == 6
    assert report["qualified"] == 6
    assert report["final_count"] == 2


def test_video_requirement_is_skipped_when_requested(tmp_path):
    job = strong_job(description="Remote data internship using Python and SQL. Stipend 3000 per month. Please record a video introduction.")
    report = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(avoid_video=True),
        search=_search([job]),
        fetcher=False,
    )
    assert report["final_count"] == 0
    assert report["rejection_counts"].get("Mandatory video requirement") == 1


def test_one_unavailable_source_keeps_the_other_results(tmp_path):
    report = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(),
        search=_search(
            [strong_job()],
            [{"name": "Indeed", "count": 0, "status": "unavailable", "note": "blocked"}, {"name": "Unstop", "count": 1, "status": "ok", "note": ""}],
        ),
        fetcher=False,
    )
    assert report["final_count"] == 1
    assert report["source_report"][0]["status"] == "unavailable"
    assert report["opportunities"][0]["company"] == "Northwind"


def test_resume_extract_does_not_invent_fields():
    from jobagent.resume_extract import extract_resume

    extracted = extract_resume(
        "Ada Lovelace\nada@example.com\n+1 415 555 0100\n\nSkills\nPython, SQL\n\nEducation\nBSc Statistics, State University, 2024\n\nProjects\nCity Lab dashboard\n"
    )
    assert extracted["full_name"] == "Ada Lovelace"
    assert extracted["email"] == "ada@example.com"
    assert "Python" in extracted["skills"]
    assert extracted["degree"]
    assert "COBOL" not in extracted["skills"]


def test_why_matches_uses_only_profile_evidence(tmp_path):
    job = strong_job(description="Remote data internship using Python and SQL. COBOL is required. Stipend 3000 per month.")
    reasons = [item.casefold() for item in why_matches(job, strong_profile(tmp_path))]
    assert "python" in reasons
    assert "cobol" not in reasons


def test_unstated_pay_stays_unless_disclosure_is_required(tmp_path):
    quiet = strong_job(
        company="Quiet",
        url="https://jobs.example.com/quiet",
        apply_url="https://jobs.example.com/quiet",
        description="Remote data internship using Python and SQL.",
        salary_min=None,
        salary_text="",
        salary_period="",
    )
    kept = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(minimum_stipend=1000),
        search=_search([quiet]),
        fetcher=False,
    )
    assert kept["final_count"] == 1
    assert kept["opportunities"][0]["compensation"] == "Compensation not disclosed"
    dropped = analyze_job_market(
        strong_profile(tmp_path),
        strong_settings(minimum_stipend=1000, require_disclosed_pay=True),
        search=_search([quiet]),
        fetcher=False,
    )
    assert dropped["final_count"] == 0
    assert dropped["rejection_counts"].get("Compensation was not disclosed") == 1


def test_unstop_live_listing_with_a_past_deadline_is_expired():
    payload = {
        "data": {
            "data": [
                {
                    "id": 1767658,
                    "title": "Cybersecurity Research Internship",
                    "public_url": "internships/cybersecurity-research-internship-vishvena-1767658",
                    "organisation": {"name": "Vishvena Techno Solutions Pvt. Ltd."},
                    "status": "LIVE",
                    "regn_open": 1,
                    "region": "online",
                    "subtype": "internships",
                    "details": "<p>Remote research internship.</p>",
                    "approved_date": "2026-10-01T00:00:00+05:30",
                    "jobDetail": {
                        "type": "wfh",
                        "min_salary": 2000,
                        "currency": "fa-rupee",
                        "show_salary": 1,
                        "not_disclosed": False,
                        "pay_in": "monthly",
                    },
                    "regnRequirements": {"end_regn_dt": "2026-10-14T23:57:00+05:30"},
                    "required_skills": [{"name": "Linux"}],
                }
            ]
        }
    }
    jobs = parse_unstop(payload)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Vishvena Techno Solutions Pvt. Ltd."
    assert job.salary_min == 2000
    assert job.salary_currency == "INR"
    assert job.workplace == "remote"
    assert job.availability_status == ""
    assert availability(job, NOW) == "EXPIRED"


def test_upwork_block_returns_no_listings(monkeypatch):
    class Response:
        status_code = 403
        text = "forbidden"

    monkeypatch.setattr("jobagent.search._polite", lambda _client, _url: Response())
    jobs, note = fetch_upwork(None, ["cybersecurity"])
    assert jobs == []
    assert note == "blocked"


def test_verify_page_does_not_call_a_blocked_url_active(tmp_path):
    from jobagent.intelligence import verify_page

    job = strong_job()

    def fetcher(_url):
        return 403, "captcha access denied"

    assert verify_page(job, fetcher) == "UNKNOWN"
    assert job.official_application_verified is False
