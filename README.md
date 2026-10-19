# AI Job Finder

<<<<<<< HEAD
> An AI-powered job and internship discovery platform that analyzes your resume, understands your preferences, searches multiple sources, and ranks the opportunities that best match your profile.

<p align="center">

**Find the right opportunities without manually searching dozens of job boards.**

</p>

---

## 🚀 Overview

**AI Job Finder** is an open-source platform designed to simplify the job and internship discovery process.

Instead of manually searching multiple job portals, comparing hundreds of listings, and checking whether each opportunity matches your profile, AI Job Finder analyzes your resume and preferences and helps you discover the most relevant opportunities.

The system is designed around three principles:

- **Personalized** — recommendations are based on your actual resume and preferences.
- **Multi-source** — opportunities can be collected from multiple job platforms and company career pages.
- **Transparent** — every recommendation shows why it matches your profile and provides a direct application link.

> AI Job Finder is a job discovery and recommendation platform. Applications are completed by the user on the employer's official website.

---

## ✨ Features

### 🧠 AI Resume Analysis

Upload your resume and automatically extract relevant information such as:

- Education
- Skills
- Programming languages
- Frameworks
- Certifications
- Projects
- Experience
- Internship experience
- Preferred domains

The extracted profile can be reviewed and edited by the user.

---

### 🎯 Personalized Job Matching

AI compares your profile against job requirements and generates a relevance score.

Example:

```text
94% Match

✓ Python
✓ Networking
✓ Linux
✓ Cybersecurity
✓ Relevant projects

Potential gap:
△ SIEM experience preferred
=======
AI Job & Internship Finder searches public listings, ranks them against a resume, and gives each result a direct application link. **Apply** opens the employer’s page in a new tab. This application does not fill or submit applications.

The browser site and the API are separate:

- `frontend/` is the static site for Netlify
- `backend/` is the Flask API for Render

Launched from Trident Tech Labs.

## What stayed the same

- Resume upload, resume reading, and profile confirmation
- Job search, source reporting, and match scoring
- Closest matches when nothing clears every filter, each with a real apply URL
- Job details and the direct application link
- Unpaid roles, fee requests, the wrong sector, and the wrong workplace stay hidden

No account or Google sign-in is required. Each browser gets its own saved resume and searches.

Search does not invent employers, skills, pay, or URLs.

## Layout

```
frontend/     HTML, CSS, JavaScript, and the Netlify build
backend/      Flask app, jobagent package, and Python dependencies
tests/        Local tests
data/         Private profile and searches. Not committed.
```

## Run it on this computer

Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
SERVE_FRONTEND=1 DATA_DIR="$PWD/data" PORT=47321 .venv/bin/python backend/app.py
```

Open http://127.0.0.1:47321. `SERVE_FRONTEND=1` makes the API serve `frontend/` on the same origin, so cookies work over plain HTTP. On Windows, double-click `run.bat`.

Copy `.env.example` to `.env` when you want those values loaded at startup. A variable already set in the environment is left as it is.

The existing profile lives in `data/` at the repository root. Set `DATA_DIR` to that folder. If `DATA_DIR` is unset, the API uses `backend/data`.

## Frontend environment

| Variable | Where | Purpose |
| --- | --- | --- |
| `API_URL` | Netlify | Public Render URL, no trailing slash. Example: `https://ai-job-finder-api.onrender.com` |
| `VITE_API_URL` | Netlify | Accepted instead of `API_URL` |

The Netlify build writes `frontend/config.js`. An empty value means same-origin, which is only for a local API that also serves the pages. A production Netlify build stops if the URL is missing.

## Backend environment

| Variable | Required in production | Purpose |
| --- | --- | --- |
| `PORT` | Set by Render | Port the API listens on. Local default is `47321`. |
| `BIND_HOST` | No | Defaults to `0.0.0.0`. |
| `APP_ENV` | Yes | `production` turns debug off and uses a Secure, SameSite=None session cookie. |
| `DATA_DIR` | Yes | Persistent directory. Render disk mount: `/var/data`. |
| `FRONTEND_ORIGIN` | Yes | Comma-separated Netlify origins, for example `https://your-site.netlify.app`. CORS allows only these origins. There is no `*` default. |
| `SECRET_KEY` | Yes | Session signing key. Render can generate it. If unset locally, a key is stored in `DATA_DIR/secret.key`. |
| `ALLOWED_HOSTS` | When using a custom domain | Comma-separated hostnames. `127.0.0.1` and `localhost` are the local default. On Render, `RENDER_EXTERNAL_HOSTNAME` and `*.onrender.com` are allowed as well. |
| `SESSION_COOKIE_SAMESITE` | No | Override. Production default is `None`. |
| `SESSION_COOKIE_SECURE` | No | Override. Production default is on. |
| `FLASK_DEBUG` | No | Local only. Forced off when `APP_ENV=production` or `RENDER=true`. |
| `SERVE_FRONTEND` | No | `1` serves `frontend/` from Flask. Leave unset on Render. |
| `OPENAI_API_KEY` | No | Optional answers. Search runs without it. |
| `OPENAI_BASE_URL` | No | Default `https://api.openai.com/v1`. |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini`. |

`GET /api/health` returns `{"status":"ok"}`.

## Netlify

- Base directory: `frontend` (also set in the root `netlify.toml`)
- Build command: `node scripts/write-config.js`
- Publish directory: `.` relative to `frontend` (the repository root publishes `frontend/`)
- Node 20
- Environment variable: `API_URL` = the Render service URL

The site is a set of HTML pages. No SPA redirect is required.

## Render

`render.yaml` describes one Python web service:

- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`
- Health check: `/api/health`
- Disk: `jobfinder-data` mounted at `/var/data`
- `DATA_DIR=/var/data`
- `APP_ENV=production`
- Set `FRONTEND_ORIGIN` to the exact Netlify origin after the first frontend deploy

The API listens on `0.0.0.0` and `$PORT`. Debug is off when Render sets `RENDER=true`.

Attach the disk before relying on saved profiles. Without it, Render’s filesystem is replaced on each deploy and uploaded resumes disappear.

### Playwright

The running API does not import Playwright and does not launch a browser. Production `backend/requirements.txt` does not include it, so the Render build does not need `playwright install`.

`backend/jobagent/apply.py` can still fill a local sample form in tests. That path is not wired to search or to the Apply button. To run it on a development machine:

```bash
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m playwright install chromium
```

Do not add that install step to the Render build.

## Uploads and logs

Resumes must be PDF, DOCX, TXT, or MD, 5 MB or smaller, and the bytes must match that type. The API refuses a body over 8 MB. Profile responses omit the resume text and the file path. Logs record short status lines. Email addresses in errors are redacted, and resume text is not written to the log.

## Tests

```bash
.venv/bin/python -m pytest
```

The tests use local samples. They do not submit applications to employers.

## Temporary public link

`start_tunnel.py` is a password gate in front of the local API. It is not the Netlify or Render deployment. Start the API first, then:

```bash
.venv/bin/python start_tunnel.py
```
>>>>>>> 0634dd5 (separate frontend and backend for deployment)

Close it with `stop_tunnel.py`. The local page does not ask for the tunnel password.
