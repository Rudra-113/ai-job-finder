import json
from datetime import datetime, timezone

import httpx

from jobagent.answers import answer_question, grounded, profile_corpus, years_for
from jobagent.gmail_otp import build_query, extract_otp
from jobagent.models import Secrets
from jobagent.profile import extract_cv_text, parse_experience
from jobagent.search import dedupe_jobs, parse_greenhouse, parse_remotive
from jobagent.models import Job
from jobagent.store import Store
from jobagent.textutil import job_identity
from tests.conftest import strong_job, strong_profile


def test_otp_extraction_ignores_unrelated_numbers():
    assert extract_otp("Your verification code is 482193") == "482193"
    assert extract_otp("Use OTP 9912 to continue") == "9912"
    assert extract_otp("Your code is 123456") == "123456"
    assert extract_otp("Invoice 2026 and order 55119") is None
    assert extract_otp("The postal code is 94107") is None


def test_gmail_query_is_narrow():
    query = build_query(
        ["greenhouse.io", "remotive.com"],
        datetime(2026, 10, 17, tzinfo=timezone.utc),
    )
    assert "after:" in query
    assert "otp" in query
    assert "from:greenhouse.io" in query
    assert "from:remotive.com" not in query
    assert "in:inbox" not in query


def test_grounding_rejects_invented_employers_and_numbers():
    corpus = "I used Python at City Lab."
    assert grounded("I used Python at City Lab.", ["Python at City Lab"], corpus)
    assert not grounded("I have 12 years at NASA.", ["Python at City Lab"], corpus)
    assert not grounded("I used Python at City Lab.", [], corpus)


def test_years_are_rounded_down():
    profile = strong_profile_without_file()
    profile.experience_raw = "Analyst | Lab | 2024-01 | 2025-07 | Python"
    assert years_for(profile, "Python") == "1"
    profile.experience_raw = "Analyst | Lab | 2024-06 | 2024-08 | Python"
    assert years_for(profile, "Python") == "less than 1"
    assert years_for(profile, "Kubernetes") is None


def test_unknown_required_question_is_not_invented(tmp_path):
    profile = strong_profile(tmp_path)
    called = {"hit": False}

    def handler(_request):
        called["hit"] = True
        raise AssertionError("API should not be called")

    answer = answer_question(
        "What is your notice period?",
        True,
        profile,
        strong_job(),
        Secrets(api_key=""),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert answer.action == "stop"
    assert called["hit"] is False
    profile.extra_facts = "Notice period: 4 weeks"
    answered = answer_question("What is your notice period?", True, profile, strong_job(), Secrets())
    assert answered.value == "4 weeks"


def test_llm_answer_must_quote_the_profile(tmp_path):
    profile = strong_profile(tmp_path)
    corpus = profile_corpus(profile)

    def ok(request):
        assert "NASA" not in json.loads(request.content)["messages"][1]["content"] or "NASA" in corpus
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "Built a Python data dashboard for City Lab.",
                                "citations": ["Built a Python data dashboard for City Lab."],
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    answer = answer_question(
        "Which dashboard did you build?",
        True,
        profile,
        strong_job(),
        Secrets(api_key="test-key", api_base="https://example.invalid/v1", api_model="test"),
        httpx.Client(transport=httpx.MockTransport(ok)),
    )
    assert answer.action == "fill"
    assert "NASA" not in answer.value

    def invented(_request):
        body = {
            "choices": [
                {"message": {"content": json.dumps({"answer": "I led NASA for 12 years.", "citations": ["City Lab"]})}}
            ]
        }
        return httpx.Response(200, json=body)

    rejected = answer_question(
        "Which dashboard did you build?",
        True,
        profile,
        strong_job(),
        Secrets(api_key="test-key", api_base="https://example.invalid/v1"),
        httpx.Client(transport=httpx.MockTransport(invented)),
    )
    assert rejected.action == "stop"


def test_cv_text_and_experience_rows(tmp_path):
    from docx import Document

    document = Document()
    document.add_paragraph("Python internship")
    path = tmp_path / "cv.docx"
    document.save(path)
    assert "Python internship" in extract_cv_text(path)
    text = tmp_path / "cv.txt"
    text.write_text("plain cv", encoding="utf-8")
    assert extract_cv_text(text) == "plain cv"
    rows = parse_experience("Analyst | Lab | 2024-01 | 2025-01 | Python\nnot a row")
    assert rows[0].company == "Lab"
    assert len(rows) == 1


def test_store_blocks_the_same_job_and_recovers_a_crash(tmp_path):
    store = Store(tmp_path)
    job = strong_job()
    assert not store.blocks(job)
    store.upsert(
        {
            "id": "abc",
            "company": job.company,
            "role": job.title,
            "url": job.url,
            "url_keys": [job.url],
            "identity": job_identity(job),
            "status": "submitted",
            "blocks_retry": True,
        }
    )
    assert store.blocks(job)
    assert store.blocks(strong_job(url="https://other.example/jobs/1", apply_url="https://other.example/jobs/1"))
    store.upsert({"id": "running", "status": "applying", "blocks_retry": True, "url": "https://jobs.example.com/paused"})
    store.recover()
    recovered = [row for row in store.records() if row["id"] == "running"][0]
    assert recovered["status"] == "needs_user"
    assert recovered["blocks_retry"] is True


def test_parsers_and_official_preference():
    jobs = parse_remotive(
        {
            "jobs": [
                {
                    "company_name": "Mitre Media",
                    "title": "Tech Lead",
                    "url": "https://remotive.com/remote-jobs/example",
                    "description": "<p>Python role. Apply at https://job-boards.greenhouse.io/example/jobs/1</p>",
                    "category": "Software Development",
                    "tags": ["python"],
                    "job_type": "full_time",
                    "candidate_required_location": "USA",
                    "salary": "$170k - $200k",
                    "publication_date": "2026-10-14T20:33:44",
                }
            ]
        }
    )
    assert jobs[0].workplace == "remote"
    assert "greenhouse.io" in jobs[0].apply_url
    greenhouse = parse_greenhouse(
        {"jobs": [{"title": "Account Executive", "absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/1", "location": {"name": "Remote, France"}, "content": "<p>Sales</p>", "company_name": "GitLab"}]},
        "GitLab",
    )
    assert greenhouse[0].company == "GitLab"
    assert greenhouse[0].workplace == "remote"
    board = Job(source="greenhouse", company="Acme", title="Engineer", url="https://job-boards.greenhouse.io/acme/jobs/1", location="Remote", workplace="remote")
    board_copy = Job(source="remotive", company="Acme", title="Engineer", url="https://remotive.com/acme", location="Remote", workplace="remote")
    chosen = dedupe_jobs([board_copy, board])
    assert len(chosen) == 1
    assert chosen[0].source == "greenhouse"


def strong_profile_without_file():
    from jobagent.profile import Profile

    return Profile(skills=["Python"], experience_raw="Analyst | Lab | 2024-01 | 2025-07 | Python")
