# Job Agent

A private job and internship agent that runs only on your Windows computer. You set a sector, roles, and pay floor. It searches public listings until you click Stop, scores them against your CV, and fills one application at a time. It does not submit until you click Submit.

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

On **Search**, confirm the sector, roles, minimum stipend, and minimum match score, then click **Start continuous search**.

The agent searches until you click **Stop**. It fills one matching application at a time and leaves the browser on that form. The page shows the company, role, match score, pay, location, posting date, filled fields, answered questions, and anything that needs your input. It submits only when you click **Submit**. **Skip** closes the form without sending it. **Edit / Continue** writes answers you type, one per line as `Question: answer`. **Open application** opens the listing URL.

Missing pay is kept and marked unknown. Unpaid roles are skipped. A stated stipend below your minimum is skipped. Hybrid roles are skipped unless you enable hybrid. On-site roles are skipped when Remote is selected.

The counters are Found, Qualified, Needs review, Filled, Submitted, Skipped, and Failed. Each submitted application lists the company, role, date, application URL, match score, and status.

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
- Apply to an unpaid role, or to a stated stipend below your minimum
- Treat missing pay as a reason to skip the listing
- Pay an application, training, or program fee
- Bypass CAPTCHA, security checks, or login walls
- Create accounts or store a password for a job site
- Store your Gmail password, or read your whole inbox
- Apply to the same job twice
- Listen on a public address, or send your CV and profile anywhere except the application page and, if you added a key, the answer API

## Limits

- Closed listings and listings past their deadline are skipped. A missing posting date is not, by itself, a reason to skip
- Search continues until you click Stop. One form is open at a time. There is no application cap and no 30-minute wait
- Hourly and weekly pay are counted only when the listing says full-time. The low end of a range is used. Currency is not converted
- Workday and Taleo pages stop at the login wall
- Duplicate protection lives in `data\applications.json`. Deleting that file allows the same job to be considered again

Sources that expose a public listing feed are searched with several role phrases, including your own roles: Remotive, Remote OK, Arbeitnow, The Muse, Jobicy, Himalayas, LinkedIn's public guest listings, Internshala, and Greenhouse, Lever, and Ashby pages for preferred companies. Indeed, Naukri, Foundit, Cutshort, and Wellfound are checked only when a public page actually contains listings. Many of those sites hide jobs behind a login or a block, and this agent does not bypass that. It does not see every job on the internet, and it does not republish listings.

## Files on this computer

Everything private is in the `data` folder next to `app.py`:

- `profile.json`, `settings.json`, `applications.json`, `secrets.json`
- `cv\` for your CV
- `gmail_client_secret.json` and `gmail_token.json`
- `agent.log` with company, role, and status only
- `reviews\` for a screenshot when an application needs you

Keep this folder on your computer. It is not part of the program files you would share.

## Temporary link from another computer

The agent stays on this computer. A password gate on `127.0.0.1:47322` forwards to `127.0.0.1:47321` only after a sign-in. A Cloudflare Quick Tunnel publishes that gate, not a deployed copy of the app.

Install cloudflared once. On Windows:

```bat
winget install --id Cloudflare.cloudflared
```

Start the agent first (`run.bat`). Then:

```bat
.venv\Scripts\python start_tunnel.py
```

The window prints the public `https://….trycloudflare.com` address, the username `jobagent`, and a password. The password is saved in `data\tunnel_password`. It is not your Gmail password. The browser asks for it before any page loads. Gmail tokens stay in `data` and are not served as files.

On this computer, [http://127.0.0.1:47321](http://127.0.0.1:47321) stays open without that password.

Close the tunnel:

```bat
.venv\Scripts\python stop_tunnel.py
```

You can also close the Command Prompt that is running `start_tunnel.py` only when you started cloudflared in that same window. `stop_tunnel.py` is the reliable way: it stops cloudflared and the password gate, and leaves the job agent running. The public URL stops working as soon as the tunnel process exits. Quick Tunnels are temporary; a new start prints a new URL.

Traffic through the public URL passes Cloudflare. Close the tunnel when you are finished. Anyone who has the password can use the agent.

## Tests

```bat
.venv\Scripts\python -m pytest
```

The tests use local sample forms. They do not submit applications to real employers.

## If you are not on Windows

The same steps work with `python3 -m venv .venv` and `.venv/bin/python`. On a machine with no display, the browser runs hidden. Set `JOBAGENT_HEADLESS=0` to show it when a display is available. Windows shows the browser unless `JOBAGENT_HEADLESS=1`.

Flask is only the local page. The optional Cloudflare link is a temporary tunnel to the password gate, not a hosted copy of the app.
