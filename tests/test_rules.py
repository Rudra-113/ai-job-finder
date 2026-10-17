from datetime import timedelta

from jobagent.criteria import sector_matches
from jobagent.filters import screen
from jobagent.matcher import score_job
from jobagent.safety import mentions_fee
from jobagent.textutil import canonical_url, company_slugs, parse_salary_text
from tests.conftest import NOW, strong_job, strong_profile, strong_settings


def test_salary_parser_knows_periods_and_refuses_guesses():
    assert parse_salary_text("$3,000 per month") == 3000
    assert parse_salary_text("Stipend 3000 per month") == 3000
    assert round(parse_salary_text("$170k - $200k per year"), 2) == round(170000 / 12, 2)
    assert parse_salary_text("Full-time $40 per hour") == 6400
    assert parse_salary_text("$40 per hour") is None
    assert parse_salary_text("competitive pay") is None
    assert parse_salary_text("2026 intern class") is None


def test_fee_language_respects_negation():
    assert mentions_fee("There is an application fee of $20.")
    assert not mentions_fee("There is no application fee for this role.")
    assert mentions_fee("Pay a training fee before you start.")


def test_it_sector_does_not_match_the_word_it():
    prose = strong_job(title="Office Coordinator", category="", tags=[], description="it is a great team")
    assert not sector_matches(prose, ["IT"])
    support = strong_job(title="IT Support Intern", category="IT", description="Help the IT team")
    assert sector_matches(support, ["IT"])


def test_canonical_url_drops_tracking():
    assert canonical_url("https://WWW.Example.com/jobs/1/?utm_source=x&gh_src=abc") == "https://example.com/jobs/1"


def test_company_slugs_drop_legal_suffixes():
    assert "gitlab" in company_slugs("GitLab, Inc.")


def test_strong_match_is_accepted(tmp_path, now):
    decision = screen(strong_job(), strong_settings(), strong_profile(tmp_path), lambda _job: False, now)
    assert decision.accept
    assert decision.score >= 80


def test_outside_sector_is_rejected_even_with_skill_overlap(tmp_path, now):
    decision = screen(
        strong_job(),
        strong_settings(sectors=["healthcare"]),
        strong_profile(tmp_path),
        lambda _job: False,
        now,
    )
    assert not decision.accept
    assert decision.reason == "Outside your sector"


def test_unpaid_fee_low_pay_and_unknown_pay(tmp_path, now):
    profile = strong_profile(tmp_path)
    settings = strong_settings()
    already = lambda _job: False
    unpaid = strong_job(
        description="This is an unpaid internship using Python and SQL.",
        salary_min=None,
        salary_period="",
        salary_text="",
    )
    assert screen(unpaid, settings, profile, already, now).reason == "Unpaid"
    fee = strong_job(description=strong_job().description + " Pay a training fee of $200 to start.")
    assert screen(fee, settings, profile, already, now).reason == "Asks for payment or looks unsafe"
    low = strong_job(salary_min=100, salary_text="100 per month", description="Remote data internship using Python and SQL. Stipend 100 per month.")
    assert screen(low, settings, profile, already, now).reason == "Pay is below your minimum"
    unknown = strong_job(salary_min=None, salary_period="", salary_text="", description="Remote data internship using Python and SQL.")
    assert screen(unknown, settings, profile, already, now).reason == "Pay is not stated, so it cannot be checked against your minimum"
    allowed = screen(unknown, strong_settings(minimum_stipend=0), profile, already, now)
    assert allowed.accept


def test_excluded_duplicate_old_and_missing_skill(tmp_path, now):
    profile = strong_profile(tmp_path)
    already = lambda _job: False
    assert screen(strong_job(), strong_settings(excluded_companies=["Northwind"]), profile, already, now).reason == "Excluded company"
    assert screen(strong_job(), strong_settings(), profile, lambda _job: True, now).reason == "Already processed"
    old = strong_job(posted_at=NOW - timedelta(days=40))
    assert screen(old, strong_settings(), profile, already, now).reason == "Older than 30 days"
    missing = strong_job()
    assert screen(missing, strong_settings(required_skills=["Kubernetes"]), profile, already, now).reason == "Does not list a required skill"


def test_skill_missing_from_profile_drops_below_threshold(tmp_path, now):
    profile = strong_profile(tmp_path)
    job = strong_job(description=strong_job().description + " Kubernetes is required.")
    decision = screen(job, strong_settings(required_skills=["Kubernetes"]), profile, lambda _job: False, now)
    assert decision.reason == "Match score below your minimum"
    assert decision.score < 70


def test_weak_title_match_stays_below_the_default_score(tmp_path, now):
    job = strong_job(
        description="General duties and team meetings for this internship.",
        tags=[],
        salary_text="Stipend 3000 per month",
    )
    decision = screen(job, strong_settings(), strong_profile(tmp_path), lambda _job: False, now)
    assert decision.reason == "Match score below your minimum"
    assert 30 <= decision.score <= 55


def test_workplace_and_location_rules(tmp_path, now):
    profile = strong_profile(tmp_path)
    already = lambda _job: False
    onsite = screen(strong_job(), strong_settings(workplace="onsite", location="Berlin"), profile, already, now)
    assert onsite.reason == "Not the workplace type you selected"
    restricted = screen(
        strong_job(location="United States"),
        strong_settings(workplace="remote", location="Berlin"),
        profile,
        already,
        now,
    )
    assert restricted.reason == "Location does not match"
    allowed = screen(
        strong_job(location="Worldwide"),
        strong_settings(workplace="remote", location="Berlin"),
        profile,
        already,
        now,
    )
    assert allowed.accept


def test_score_does_not_invent_a_preferred_company_boost_without_a_match(tmp_path):
    profile = strong_profile(tmp_path)
    plain = score_job(strong_job(), profile, strong_settings())
    boosted = score_job(strong_job(), profile, strong_settings(preferred_companies=["Northwind"]))
    assert boosted == min(100, plain + 10)
