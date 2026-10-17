# Job Agent

A private job and internship agent that runs only on your Windows computer. You set a sector, roles, and pay floor. It searches public listings, scores them against your CV, and submits applications that pass your rules. It stops and asks you only when a page is unsafe or a required fact is missing.

The page listens on [http://127.0.0.1:47321](http://127.0.0.1:47321). It does not accept connections from other computers.

## What you need

- Windows 10 or 11
- Python 3.11 or newer from [python.org](https://www.python.org/downloads/). During setup, check **Add python.exe to PATH**.
- A text-based CV: PDF, DOCX, TXT, or MD. A scanned PDF has no readable text, so scoring will be weak until you add skills and experience on the Profile page.
- Optional: an OpenAI or xAI API key, for application questions your saved facts do not already answer.
- Optional: a Google Cloud desktop OAuth client, if you want the agent to read a one-time email code.

## Run

Double-click `run.bat`, or open Command Prompt in this folder and run:

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python app.py
```

Then open [http://127.0.0.1:47321](http://127.0.0.1:47321).

Leave that window open. Closing it stops the agent. To stop a search first, click **Stop** on the Search page, then close the window.

The first run downloads Chromium into your user profile. That download is used only to fill application forms.

## Set it up

### 1. Profile

Open **Profile** and save:

- Full name (first and last), email, phone, city, and country
- Portfolio, LinkedIn, and GitHub URLs when you have them
- Work authorization and visa sponsorship. Leave these blank only if you want those questions to pause the application.
- Skills, education, experience, and projects, written as they are true
- Extra facts, one per line, as `Label: value`. Example: `Notice period: 4 weeks`
- Your CV file

Education is one school per line: `Degree | Field | School | End`

Experience is one role per line: `Title | Company | Start | End | What you did`

Dates are `YYYY-MM`. Use `present` if you still work there.

Search will not start until a full name, a valid email, and a CV are saved. The CV must contain readable text, or you must add skills or experience.

### 2. Settings

Open **Settings** and save every rule the agent must follow:

- Target sector
- Target roles
- Required skills
- Location
- Remote, onsite, hybrid, or any
- Minimum stipend, as a monthly amount
- Preferred companies
- Excluded companies
- Minimum match score, from 0 to 100

A listing outside these rules is skipped. Preferred companies also have their public Greenhouse, Lever, and Ashby career pages checked. They are not a closed list: other companies can still match from the job boards. A company whose name contains an excluded name is never opened.

### 3. Start

On **Search**, confirm the sector, roles, minimum stipend, and minimum match score, then click **Start search**.

The agent searches immediately, then again every 30 minutes, until you click **Stop**. After a listing passes your rules, the application is filled and submitted without asking you to review each one.

The page shows jobs found, jobs rejected, applications submitted, and applications failed. Each submitted application lists the company, role, date, application URL, match score, and status.

## When it stops and asks you

A job appears under **Needs you** when the agent hits:

- a CAPTCHA or human check
- an unusual identity check
- a required fact that is not on your Profile
- a request for payment
- a login or account wall
- a field it cannot fill without guessing

**Try again** opens that application once more, and the same safety checks still apply. **Don't apply** records it so it is never opened again.

## Gmail, for one-time codes only

The agent never asks for your Gmail password. Connect it only if applications email you a code.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project.
2. Enable the Gmail API.
3. Set the OAuth consent screen to **External** and **Testing**. Add your own Gmail address as a test user.
4. Create an OAuth client of type **Desktop app** and download the JSON file.
5. On Profile, choose that file and click **Save profile**.
6. Click **Connect Gmail**. A browser window opens. Sign in and allow read-only access.

The token stays in the `data` folder on this computer. It is used only after an application asks for a one-time code. The search looks at up to five recent messages that match code keywords, optionally from that employer's domain, and reads the body of the newest matching message. It does not read the rest of the inbox.

## Answer API

Most answers come from your Profile. An API key is used only for a required question that your saved facts do not cover. The answer is kept only when every cited phrase, number, and content word appears in your saved profile. Otherwise that application pauses.

On Profile, set the base URL and model, paste the key, and save. Leave the key blank on later saves to keep it. Check **Remove saved API key** to delete it.

- OpenAI: base `https://api.openai.com/v1`, and a model on your account such as `gpt-4o-mini`
- Grok: base `https://api.x.ai/v1`, and the model name shown in your xAI account

You can also copy `.env.example` to `.env` and fill the same values. The app reads `.env` when it starts. A variable already set in the environment is left as it is. A key saved on the Profile page is used ahead of both.

## What it will not do

- Invent qualifications, employers, dates, or skills
- Apply outside the sector you entered
- Apply to an unpaid role
- Apply when your minimum stipend is above 0 and the listing does not state pay
- Pay an application, training, or program fee
- Bypass CAPTCHA, security checks, or login walls
- Create accounts or store a password for a job site
- Store your Gmail password, or read your whole inbox
- Apply to the same job twice
- Listen on a public address, or send your CV and profile anywhere except the application page and, if you added a key, the answer API

## Limits

- Listings older than 30 days, or past their deadline, are skipped
- Each pass attempts at most 5 applications, then waits 30 minutes
- Hourly and weekly pay are counted only when the listing says full-time. The low end of a range is used. Currency is not converted
- Workday and Taleo pages stop at the login wall
- Duplicate protection lives in `data\applications.json`. Deleting that file allows the same job to be considered again

Sources: Remotive, Remote OK, Arbeitnow, The Muse, Jobicy, Himalayas, and public Greenhouse, Lever, and Ashby career pages for preferred companies. This app does not republish those listings.

## Files on this computer

Everything private is in the `data` folder next to `app.py`:

- `profile.json`, `settings.json`, `applications.json`, `secrets.json`
- `cv\` for your CV
- `gmail_client_secret.json` and `gmail_token.json`
- `agent.log` with company, role, and status only
- `reviews\` for a screenshot when an application needs you

Keep this folder on your computer. It is not part of the program files you would share.

## Tests

```bat
.venv\Scripts\python -m pytest
```

The tests use local sample forms. They do not submit applications to real employers.

## If you are not on Windows

The same steps work with `python3 -m venv .venv` and `.venv/bin/python`. On a machine with no display, the browser runs hidden. Set `JOBAGENT_HEADLESS=0` to show it when a display is available. Windows shows the browser unless `JOBAGENT_HEADLESS=1`.

Flask is only the local page. There is no public site.
