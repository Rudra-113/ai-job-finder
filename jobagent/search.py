"""Read public job feeds and career pages. This does not republish the listings."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote_plus, urlsplit

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
    "linkedin": 9,
    "internshala": 9,
}
SECURITY_QUERIES = (
    "cybersecurity intern",
    "cyber security intern",
    "security intern",
    "SOC intern",
    "SOC analyst intern",
    "VAPT intern",
    "penetration testing intern",
    "security research intern",
    "application security intern",
    "network security intern",
    "information security intern",
    "threat intelligence intern",
    "cloud security intern",
    "AI security intern",
    "cybersecurity research intern",
    "Python security intern",
    "security engineering intern",
    "vulnerability assessment intern",
    "ethical hacking intern",
    "cyber defense intern",
    "security analyst intern",
)
_HOST_GAP = 0.6
_last_hit: dict[str, float] = {}
_OFFICIAL = ("greenhouse.io", "lever.co", "ashbyhq.com")


def search_queries(settings: Settings) -> list[str]:
    """User roles, remote/India variants, and the security intern phrases."""
    raw: list[str] = []
    for role in settings.roles:
        text = role.strip()
        if not text:
            continue
        raw.append(text)
        raw.append(f"{text} remote")
        raw.append(f"{text} India")
    raw.extend(SECURITY_QUERIES)
    seen: set[str] = set()
    queries: list[str] = []
    for item in raw:
        key = item.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            queries.append(item.strip())
    return queries


def _polite(client: httpx.Client, url: str):
    host = urlsplit(url).netloc.casefold()
    last = _last_hit.get(host, 0)
    gap = _HOST_GAP - (time.time() - last)
    if gap > 0:
        time.sleep(gap)
    try:
        response = client.get(url)
    except httpx.HTTPError:
        _last_hit[host] = time.time()
        return None
    _last_hit[host] = time.time()
    return response


def _get_json(client: httpx.Client, url: str):
    response = _polite(client, url)
    if response is None:
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


def fetch_remotive(client: httpx.Client, _settings: Settings, queries: list[str] | None = None) -> tuple[list[Job], str | None]:
    unique = list(dict.fromkeys(queries or [""]))[:4]
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


def fetch_muse(client: httpx.Client, _settings: Settings, queries: list[str] | None = None) -> tuple[list[Job], str | None]:
    page = 1 + (abs(hash(tuple(queries or []))) % 5)
    payload, err = _get_json(client, f"https://www.themuse.com/api/public/jobs?page={page}")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return parse_muse(payload), None


def fetch_jobicy(client: httpx.Client, _settings: Settings) -> tuple[list[Job], str | None]:
    payload, err = _get_json(client, "https://jobicy.com/api/v2/remote-jobs?count=50")
    if err or not isinstance(payload, dict):
        return [], err or "unavailable"
    return parse_jobicy(payload), None


def fetch_himalayas(client: httpx.Client, _settings: Settings, queries: list[str] | None = None) -> tuple[list[Job], str | None]:
    found: list[Job] = []
    error = None
    for query in (queries or [""])[:3]:
        url = "https://himalayas.app/jobs/api?limit=20&q=" + quote_plus(query)
        payload, err = _get_json(client, url)
        if err:
            error = err
            continue
        if isinstance(payload, dict):
            found.extend(parse_himalayas(payload))
    return _newest(found, 60), error if not found else None


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


def parse_linkedin_guest(html: str) -> list[Job]:
    jobs: list[Job] = []
    chunks = re.split(r'data-entity-urn="urn:li:jobPosting:', html or "")
    for chunk in chunks[1:]:
        link = re.search(r'href="(https://[^"]+/jobs/view/[^"?]+)', chunk)
        title = re.search(r'class="sr-only">\s*([^<]+?)\s*</span>', chunk, re.S)
        company = re.search(r'base-search-card__subtitle[\s\S]{0,400}?>([^<]+)</', chunk)
        if not link or not title:
            continue
        place = re.search(r'job-search-card__location[\s\S]{0,200}?>([^<]+)<', chunk)
        location = unescape(place.group(1)).strip() if place else "India"
        name = unescape(company.group(1)).strip() if company else ""
        if not name:
            slug = link.group(1).rstrip("/").split("/")[-1]
            at = re.search(r"-at-(.+)-(\d+)$", slug)
            name = at.group(1).replace("-", " ") if at else ""
        job = _job(
            "linkedin",
            name,
            unescape(title.group(1)).strip(),
            unescape(link.group(1)),
            location=location,
            description=unescape(title.group(1)).strip(),
            workplace="unknown",
        )
        if job:
            jobs.append(job)
    return jobs


def parse_internshala(html: str) -> list[Job]:
    jobs: list[Job] = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html or "", re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        for item in data.get("itemListElement") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            title = re.sub(r"\s*-\s*Internship.*$", "", name, flags=re.I).strip() or name
            remote = bool(re.search(r"wfh|work from home|remote", name, re.I))
            company = ""
            slug = url.rstrip("/").split("/")[-1]
            match = re.search(r"-at-([a-z0-9-]+?)(\d*)$", slug)
            if match:
                company = match.group(1).replace("-", " ").strip()
            job = _job(
                "internshala",
                company or "Internshala listing",
                title,
                url,
                location="India",
                description=name,
                workplace="remote" if remote else "unknown",
                remote=True if remote else None,
            )
            if job:
                jobs.append(job)
    return jobs


def fetch_linkedin(client: httpx.Client, queries: list[str]) -> tuple[list[Job], str | None]:
    found: list[Job] = []
    for query in queries[:4]:
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords="
            + quote_plus(query)
            + "&location=India&start=0"
        )
        response = _polite(client, url)
        if response is None or response.status_code in {401, 403, 429, 999}:
            return found, "blocked"
        if response.status_code != 200:
            return found, "unavailable"
        if "authwall" in response.text[:1500].casefold() or "captcha" in response.text[:1500].casefold():
            return found, "blocked"
        found.extend(parse_linkedin_guest(response.text))
    return found, None if found else "no public listings"


def fetch_internshala(client: httpx.Client, queries: list[str]) -> tuple[list[Job], str | None]:
    found: list[Job] = []
    for query in queries[:2]:
        slug = re.sub(r"[^a-z0-9]+", "-", query.casefold()).strip("-")
        response = _polite(client, f"https://internshala.com/internships/keywords-{slug}/")
        if response is None or response.status_code in {401, 403, 429}:
            return found, "blocked"
        if response.status_code != 200:
            return found, "unavailable"
        found.extend(parse_internshala(response.text))
    return found, None if found else "no public listings"


def parse_unstop(payload: dict) -> list[Job]:
    page = payload.get("data") if isinstance(payload, dict) else None
    rows = page.get("data") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        return []
    jobs: list[Job] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        org = item.get("organisation") if isinstance(item.get("organisation"), dict) else {}
        public = str(item.get("public_url") or "").lstrip("/")
        url = f"https://unstop.com/{public}" if public else ""
        detail = item.get("jobDetail") if isinstance(item.get("jobDetail"), dict) else {}
        regs = item.get("regnRequirements") if isinstance(item.get("regnRequirements"), dict) else {}
        workplace = "unknown"
        if str(detail.get("type") or "").casefold() in {"wfh", "remote"} or str(item.get("region") or "").casefold() == "online":
            workplace = "remote"
        disclosed = detail.get("not_disclosed") is not True and detail.get("show_salary")
        salary = as_float(detail.get("min_salary")) if disclosed else None
        currency = "INR" if "rupee" in str(detail.get("currency") or "") else ""
        skills = []
        for skill in item.get("required_skills") or []:
            if isinstance(skill, dict) and skill.get("name"):
                skills.append(str(skill["name"]))
        closed = item.get("regn_open") in {0, False} or str(item.get("status") or "").upper() not in {"", "LIVE"}
        job = _job(
            "unstop",
            str(org.get("name") or ""),
            str(item.get("title") or ""),
            url,
            description=clean_html(str(item.get("details") or "")),
            workplace=workplace,
            remote=True if workplace == "remote" else None,
            employment=str(item.get("subtype") or ""),
            salary_min=salary,
            salary_period="month" if detail.get("pay_in") == "monthly" and salary is not None else "",
            salary_currency=currency,
            posted_at=parse_date(item.get("approved_date") or item.get("updated_at")),
            deadline=parse_date(regs.get("end_regn_dt")),
            tags=skills,
            skills=skills,
            source_listing_id=str(item.get("id") or ""),
            availability_status="EXPIRED" if closed else "",
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_unstop(client: httpx.Client, queries: list[str]) -> tuple[list[Job], str | None]:
    found: list[Job] = []
    error = None
    for query in (queries or ["intern"])[:3]:
        url = (
            "https://unstop.com/api/public/opportunity/search-result?opportunity=internships&per_page=20&searchTerm="
            + quote_plus(query)
        )
        response = _polite(client, url)
        if response is None or response.status_code in {401, 403, 429}:
            return found, "blocked"
        if response.status_code != 200:
            error = "unavailable"
            continue
        try:
            payload = response.json()
        except ValueError:
            error = "unavailable"
            continue
        found.extend(parse_unstop(payload))
    return found, error if not found else None


def fetch_upwork(client: httpx.Client, queries: list[str]) -> tuple[list[Job], str | None]:
    """Public RSS only. A 403 or challenge returns nothing and is not bypassed."""
    query = quote_plus(queries[0] if queries else "intern")
    response = _polite(client, f"https://www.upwork.com/ab/feed/jobs/rss?q={query}&sort=recency")
    if response is None or response.status_code in {401, 403, 429, 503}:
        return [], "blocked"
    if response.status_code != 200:
        return [], "unavailable"
    text = response.text[:2500].casefold()
    if "captcha" in text or "access denied" in text or "just a moment" in text:
        return [], "blocked"
    if "<item>" not in response.text.casefold():
        return [], "no public listings"
    jobs: list[Job] = []
    for chunk in re.findall(r"<item>(.*?)</item>", response.text, flags=re.I | re.S)[:20]:
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", chunk, re.I | re.S)
        link = re.search(r"<link>(.*?)</link>", chunk, re.I | re.S)
        if not title or not link:
            continue
        job = _job("upwork", "Upwork client", unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(), unescape(link.group(1)).strip())
        if job:
            jobs.append(job)
    return jobs, None if jobs else "no public listings"


def fetch_extra_boards(client: httpx.Client, queries: list[str]) -> tuple[list[Job], list[str]]:
    """Try public pages. A block or an empty shell is recorded and not bypassed."""
    warnings: list[str] = []
    query = quote_plus(queries[0] if queries else "intern")
    checks = (
        ("Indeed", f"https://www.indeed.com/jobs?q={query}&l=India&fromage=14"),
        ("Naukri", f"https://www.naukri.com/{(queries[0] if queries else 'intern').casefold().replace(' ', '-')}-jobs"),
        ("Foundit", f"https://www.foundit.in/search/{(queries[0] if queries else 'intern').casefold().replace(' ', '-')}-jobs"),
        ("Cutshort", f"https://cutshort.io/jobs/{(queries[0] if queries else 'intern').casefold().replace(' ', '-')}"),
        ("Wellfound", f"https://wellfound.com/jobs?q={query}"),
    )
    for name, url in checks:
        response = _polite(client, url)
        if response is None or response.status_code in {401, 403, 429, 503}:
            warnings.append(f"{name} blocked public access")
            continue
        if response.status_code != 200:
            warnings.append(f"{name} unavailable")
            continue
        text = response.text[:4000].casefold()
        if "captcha" in text or "access denied" in text:
            warnings.append(f"{name} blocked public access")
            continue
        warnings.append(f"{name} had no public listing feed to read")
    return [], warnings


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


def _run_fetch(fn, settings: Settings, queries: list[str]) -> tuple[list[Job], str | None]:
    with httpx.Client(timeout=12.0, follow_redirects=True, headers=HEADERS) as client:
        try:
            return fn(client, settings, queries)
        except TypeError:
            return fn(client, settings)


def _source_row(name: str, count: int, note: str | None) -> dict:
    if note in {"blocked", "unavailable"} or (note or "").startswith("blocked"):
        status = "unavailable"
    elif count:
        status = "ok"
    elif note:
        status = "empty"
    else:
        status = "empty"
    return {"name": name, "count": count, "status": status, "note": note or ""}


def search_all_sources(settings: Settings, queries: list[str] | None = None) -> tuple[list[Job], list[str], list[dict]]:
    """Search every configured public source. One failure does not cancel the others."""
    warnings: list[str] = []
    jobs: list[Job] = []
    report: list[dict] = []
    chosen = list(queries or search_queries(settings)[:8])
    fetches = (
        ("Remotive", fetch_remotive),
        ("Remote OK", fetch_remoteok),
        ("Arbeitnow", fetch_arbeitnow),
        ("The Muse", fetch_muse),
        ("Jobicy", fetch_jobicy),
        ("Himalayas", fetch_himalayas),
    )

    def extra(client: httpx.Client, _settings: Settings, query_list: list[str] | None = None) -> tuple[list[Job], str | None]:
        query_list = query_list or []
        batch: list[Job] = []
        messages = []
        for name, fn in (
            ("LinkedIn", fetch_linkedin),
            ("Internshala", fetch_internshala),
            ("Unstop", fetch_unstop),
            ("Upwork", fetch_upwork),
        ):
            try:
                found, note = fn(client, query_list)
            except Exception:
                found, note = [], "unavailable"
            batch.extend(found)
            report.append(_source_row(name, len(found), note))
            if note and note not in {"no public listings"}:
                messages.append(f"{name} {note}")
            elif note:
                messages.append(f"{name} had no public listing feed to read")
        _empty, notes = fetch_extra_boards(client, query_list)
        for note in notes:
            source_name = note.split(" ", 1)[0]
            status_note = "blocked" if "blocked" in note else "empty" if "no public" in note else "unavailable"
            report.append(_source_row(source_name, 0, status_note))
        messages.extend(notes)
        return batch, "; ".join(messages) if messages else None

    workers = [*fetches, ("More boards", extra)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(_run_fetch, fn, settings, chosen): name for name, fn in workers}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                batch, error = future.result()
            except Exception:
                warnings.append(name)
                if name != "More boards":
                    report.append(_source_row(name, 0, "unavailable"))
                continue
            if name != "More boards":
                report.append(_source_row(name, len(batch), "unavailable" if error and not batch else None))
            if error:
                warnings.append(f"{name}: {error}" if name == "More boards" else name)
            jobs.extend(batch)
    company_count = 0
    companies = settings.preferred_companies[:15]
    if companies:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=HEADERS) as client:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(fetch_company_jobs, client, company) for company in companies]
                for future in as_completed(futures):
                    try:
                        found = future.result()
                    except Exception:
                        continue
                    company_count += len(found)
                    jobs.extend(found)
    report.append(_source_row("Company Careers", company_count, None if company_count else "empty"))
    unique = dedupe_jobs(jobs)
    unique.sort(key=lambda job: job.posted_at.timestamp() if job.posted_at else 0, reverse=True)
    return unique, warnings, report


def search_jobs(settings: Settings, queries: list[str] | None = None) -> tuple[list[Job], list[str]]:
    jobs, warnings, _report = search_all_sources(settings, queries)
    return jobs, warnings
