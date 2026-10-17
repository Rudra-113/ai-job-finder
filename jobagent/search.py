"""Read public job feeds and career pages. This does not republish the listings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import httpx

from jobagent.models import Job
from jobagent.settings import Settings
from jobagent.textutil import (
    as_bool,
    as_float,
    as_list,
    clean_html,
    company_slugs,
    find_ats_url,
    normalize_period,
    parse_date,
    workplace_from_location,
)

HEADERS = {
    "User-Agent": "PersonalJobAgent/1.0 (local; applications stay on this computer)",
    "Accept": "application/json",
}
SOURCE_RANK = {
    "greenhouse": 0,
    "lever": 1,
    "ashby": 2,
    "remotive": 3,
    "jobicy": 4,
    "himalayas": 5,
    "remoteok": 6,
    "arbeitnow": 7,
    "themuse": 8,
}
_OFFICIAL = ("greenhouse.io", "lever.co", "ashbyhq.com")


def _get_json(client: httpx.Client, url: str):
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None, "unavailable"
    if response.status_code == 404:
        return None, None
    if response.status_code != 200:
        return None, "unavailable"
    try:
        return response.json(), None
    except ValueError:
        return None, "unavailable"


def _job(source: str, company: str, title: str, url: str, **kwargs) -> Job | None:
    if not company.strip() or not title.strip() or not url.strip():
        return None
    description = kwargs.get("description") or ""
    apply_url = kwargs.get("apply_url") or find_ats_url(description) or url
    kwargs["apply_url"] = apply_url
    kwargs["description"] = description
    return Job(source=source, company=company.strip(), title=title.strip(), url=url.strip(), **kwargs)


def parse_remotive(payload: dict) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        description = clean_html(item.get("description") or "")
        job = _job(
            "remotive",
            str(item.get("company_name") or ""),
            str(item.get("title") or ""),
            str(item.get("url") or ""),
            description=description,
            location=str(item.get("candidate_required_location") or ""),
            tags=as_list(item.get("tags")),
            category=str(item.get("category") or ""),
            employment=str(item.get("job_type") or ""),
            remote=True,
            workplace="remote",
            salary_text=str(item.get("salary") or ""),
            posted_at=parse_date(item.get("publication_date")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_remoteok(payload) -> list[Job]:
    if not isinstance(payload, list):
        return []
    jobs: list[Job] = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        description = clean_html(item.get("description") or "")
        url = str(item.get("apply_url") or item.get("url") or "")
        job = _job(
            "remoteok",
            str(item.get("company") or ""),
            str(item.get("position") or ""),
            url,
            description=description,
            location=str(item.get("location") or ""),
            tags=as_list(item.get("tags")),
            remote=True,
            workplace="remote",
            posted_at=parse_date(item.get("date")) or parse_date(item.get("epoch")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_arbeitnow(payload: dict) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        remote_flag = as_bool(item.get("remote"))
        location = str(item.get("location") or "")
        description = clean_html(item.get("description") or "")
        tags = as_list(item.get("tags"))
        job = _job(
            "arbeitnow",
            str(item.get("company_name") or ""),
            str(item.get("title") or ""),
            str(item.get("url") or ""),
            description=description,
            location=location,
            tags=tags,
            category=" ".join(tags),
            employment=" ".join(as_list(item.get("job_types"))),
            remote=remote_flag,
            workplace="remote" if remote_flag else "onsite" if remote_flag is False else "unknown",
            posted_at=parse_date(item.get("created_at")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_muse(payload: dict) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        company = str((item.get("company") or {}).get("name") or "")
        description = clean_html(item.get("contents") or "")
        location = ", ".join(as_list(item.get("locations")))
        categories = as_list(item.get("categories"))
        job = _job(
            "themuse",
            company,
            str(item.get("name") or ""),
            str((item.get("refs") or {}).get("landing_page") or ""),
            description=description,
            location=location,
            tags=as_list(item.get("tags")) + as_list(item.get("levels")),
            category=" ".join(categories),
            workplace=workplace_from_location(location + " " + description[:240]),
            posted_at=parse_date(item.get("publication_date")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_jobicy(payload: dict) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        description = clean_html(item.get("jobDescription") or item.get("jobExcerpt") or "")
        industries = as_list(item.get("jobIndustry"))
        location = str(item.get("jobGeo") or "")
        job = _job(
            "jobicy",
            str(item.get("companyName") or ""),
            str(item.get("jobTitle") or ""),
            str(item.get("url") or ""),
            description=description,
            location=location,
            tags=industries,
            category=" ".join(industries),
            employment=" ".join(as_list(item.get("jobType"))),
            remote=True,
            workplace="remote",
            salary_min=as_float(item.get("salaryMin")),
            salary_max=as_float(item.get("salaryMax")),
            salary_period=normalize_period(str(item.get("salaryPeriod") or "")),
            salary_currency=str(item.get("salaryCurrency") or ""),
            posted_at=parse_date(item.get("pubDate")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_himalayas(payload: dict) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        description = clean_html(item.get("description") or item.get("excerpt") or "")
        location = ", ".join(as_list(item.get("locationRestrictions")))
        categories = as_list(item.get("categories"))
        job = _job(
            "himalayas",
            str(item.get("companyName") or ""),
            str(item.get("title") or ""),
            str(item.get("applicationLink") or item.get("guid") or ""),
            description=description,
            location=location,
            tags=categories,
            category=" ".join(as_list(item.get("parentCategories")) + categories),
            employment=str(item.get("employmentType") or ""),
            remote=True,
            workplace="remote",
            salary_min=as_float(item.get("minSalary")),
            salary_max=as_float(item.get("maxSalary")),
            salary_period=normalize_period(str(item.get("salaryPeriod") or "")),
            salary_currency=str(item.get("currency") or ""),
            posted_at=parse_date(item.get("pubDate")),
            deadline=parse_date(item.get("expiryDate")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_greenhouse(payload: dict, company_hint: str) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        location = str((item.get("location") or {}).get("name") or "")
        description = clean_html(item.get("content") or "")
        departments = as_list(item.get("departments"))
        job = _job(
            "greenhouse",
            str(item.get("company_name") or company_hint),
            str(item.get("title") or ""),
            str(item.get("absolute_url") or ""),
            description=description,
            location=location,
            category=" ".join(departments),
            workplace=workplace_from_location(location),
            posted_at=parse_date(item.get("first_published")) or parse_date(item.get("updated_at")),
            deadline=parse_date(item.get("application_deadline")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_lever(payload, company_hint: str) -> list[Job]:
    if not isinstance(payload, list):
        return []
    jobs: list[Job] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        categories = item.get("categories") or {}
        places = as_list(categories.get("allLocations"))
        location = ", ".join(places) if places else str(categories.get("location") or "")
        workplace_type = str(item.get("workplaceType") or "")
        description = item.get("descriptionPlain") or clean_html(item.get("description") or "")
        job = _job(
            "lever",
            company_hint,
            str(item.get("text") or ""),
            str(item.get("hostedUrl") or ""),
            apply_url=str(item.get("applyUrl") or item.get("hostedUrl") or ""),
            description=description,
            location=location,
            category=" ".join(
                part for part in (str(categories.get("department") or ""), str(categories.get("team") or "")) if part
            ),
            employment=str(categories.get("commitment") or ""),
            workplace=workplace_from_location(workplace_type + " " + location),
            posted_at=parse_date(item.get("createdAt")),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_ashby(payload: dict, company_hint: str) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict) or item.get("isListed") is False:
            continue
        workplace_type = str(item.get("workplaceType") or "")
        location = str(item.get("location") or "")
        if "hybrid" in workplace_type.casefold():
            workplace = "hybrid"
        elif "remote" in workplace_type.casefold() or item.get("isRemote") is True:
            workplace = "remote"
        elif workplace_type:
            workplace = "onsite"
        else:
            workplace = workplace_from_location(location)
        description = item.get("descriptionPlain") or clean_html(item.get("descriptionHtml") or "")
        job = _job(
            "ashby",
            company_hint,
            str(item.get("title") or ""),
            str(item.get("jobUrl") or ""),
            apply_url=str(item.get("applyUrl") or item.get("jobUrl") or ""),
            description=description,
            location=location,
            category=" ".join(part for part in (str(item.get("department") or ""), str(item.get("team") or "")) if part),
            employment=str(item.get("employmentType") or ""),
            remote=True if workplace == "remote" else False if workplace == "onsite" else None,
            workplace=workplace,
            posted_at=parse_date(item.get("publishedAt")),
        )
        if job:
            jobs.append(job)
    return jobs


def _newest(jobs: list[Job], limit: int) -> list[Job]:
    jobs.sort(key=lambda job: job.posted_at.timestamp() if job.posted_at else 0, reverse=True)
    return jobs[:limit]


def fetch_remotive(client: httpx.Client, settings: Settings) -> tuple[list[Job], str | None]:
    queries: list[str] = []
    for role in settings.roles[:3]:
        queries.append(role)
    if settings.sectors:
        queries.append(settings.sectors[0])
    unique = list(dict.fromkeys(queries))[:4] or [""]
    found: list[Job] = []
    error = None
    for query in unique:
        url = "https://remotive.com/api/remote-jobs?search=" + quote_plus(query)
        payload, err = _get_json(client, url)
        if err:
            error = err
            continue
        if isinstance(payload, dict):
            found.extend(parse_remotive(payload))
    return _newest(found, 80), error if not found else None


def fetch_remoteok(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://remoteok.com/api")
    if err or not isinstance(payload, list):
        return [], err or "unavailable"
    return _newest(parse_remoteok(payload), 100), None


def fetch_arbeitnow(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://www.arbeitnow.com/api/job-board-api")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return _newest(parse_arbeitnow(payload), 100), None


def fetch_muse(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://www.themuse.com/api/public/jobs?page=1")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return parse_muse(payload), None


def fetch_jobicy(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://jobicy.com/api/v2/remote-jobs?count=50")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return parse_jobicy(payload), None


def fetch_himalayas(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://himalayas.app/jobs/api?limit=50")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return parse_himalayas(payload), None


def fetch_company_jobs(client: httpx.Client, company: str) -> list[Job]:
    found: list[Job] = []
    for slug in company_slugs(company):
        greenhouse, _err = _get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if isinstance(greenhouse, dict) and greenhouse.get("jobs"):
            found.extend(parse_greenhouse(greenhouse, company))
        lever, _err = _get_json(client, f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if isinstance(lever, list) and lever:
            found.extend(parse_lever(lever, company))
        ashby, _err = _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if isinstance(ashby, dict) and ashby.get("jobs"):
            found.extend(parse_ashby(ashby, company))
        if found:
            break
    return _newest(found, 30)


def _prefer_official(job: Job) -> None:
    if any(host in (job.apply_url or "") for host in _OFFICIAL):
        return
    official = find_ats_url(job.description)
    if official:
        job.apply_url = official


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    chosen: dict[str, Job] = {}
    for job in jobs:
        _prefer_official(job)
        identity = f"{job.company.casefold()}|{job.title.casefold()}|{job.location.casefold()}|{job.workplace}"
        current = chosen.get(identity)
        if current is None or SOURCE_RANK.get(job.source, 9) < SOURCE_RANK.get(current.source, 9):
            chosen[identity] = job
        elif current is not None and not (current.salary_min or current.salary_text) and (job.salary_min or job.salary_text):
            if SOURCE_RANK.get(job.source, 9) == SOURCE_RANK.get(current.source, 9):
                chosen[identity] = job
    return list(chosen.values())


def search_jobs(settings: Settings) -> tuple[list[Job], list[str]]:
    warnings: list[str] = []
    jobs: list[Job] = []
    fetches = (
        ("Remotive", fetch_remotive),
        ("Remote OK", fetch_remoteok),
        ("Arbeitnow", fetch_arbeitnow),
        ("The Muse", fetch_muse),
        ("Jobicy", fetch_jobicy),
        ("Himalayas", fetch_himalayas),
    )
    with httpx.Client(timeout=12.0, follow_redirects=True, headers=HEADERS) as client:
        with ThreadPoolExecutor(max_workers=6) as pool:
            future_map = {pool.submit(fn, client, settings): name for name, fn in fetches}
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    batch, error = future.result()
                except Exception:
                    warnings.append(name)
                    continue
                if error:
                    warnings.append(name)
                jobs.extend(batch)
        companies = settings.preferred_companies[:15]
        if companies:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(fetch_company_jobs, client, company) for company in companies]
                for future in as_completed(futures):
                    try:
                        jobs.extend(future.result())
                    except Exception:
                        continue
    unique = dedupe_jobs(jobs)
    unique.sort(key=lambda job: job.posted_at.timestamp() if job.posted_at else 0, reverse=True)
    return unique[:200], warnings
