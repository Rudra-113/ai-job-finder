# 🚀 AI Job Finder

<p align="center">
  <strong>Find better opportunities. Faster.</strong>
</p>

<p align="center">
  An AI-powered job and internship discovery platform that analyzes your resume, understands your preferences, and helps you discover relevant opportunities.
</p>

<p align="center">
  <a href="https://sprightly-pudding-24dc69.netlify.app/">
    <img src="https://img.shields.io/badge/🚀%20Live%20Demo-Visit%20AI%20Job%20Finder-00C7B7?style=for-the-badge" alt="Live Demo">
  </a>
  <a href="https://github.com/Rudra-113/ai-job-finder">
    <img src="https://img.shields.io/badge/GitHub-Repository-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/AI-Powered-8B5CF6?style=flat-square">
  <img src="https://img.shields.io/badge/Status-Live-22C55E?style=flat-square">
  <img src="https://img.shields.io/badge/Frontend-Netlify-00C7B7?style=flat-square&logo=netlify&logoColor=white">
  <img src="https://img.shields.io/badge/Backend-Railway-0B0D0E?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black">
</p>

---

## 🌟 What is AI Job Finder?

**AI Job Finder** is an AI-powered platform designed to make finding internships and jobs easier, faster, and more personalized.

Instead of repeatedly searching job boards and manually checking whether every opportunity matches your profile, AI Job Finder analyzes your resume, understands your preferences, and helps you discover relevant opportunities.

### The idea is simple:

> **Upload your resume → Set your preferences → Discover opportunities → Apply**

---

## 🎯 Why AI Job Finder?

Finding the right internship or job can be time-consuming.

Students and job seekers often have to:

- Search across multiple platforms
- Read hundreds of job descriptions
- Compare requirements with their resume
- Check locations and eligibility
- Identify relevant roles
- Repeat the same process every day

AI Job Finder aims to reduce that friction by bringing the process into one simple workflow.

```text
Traditional Job Search

Search
  ↓
Open Job
  ↓
Read Description
  ↓
Compare Resume
  ↓
Reject / Apply
  ↓
Repeat

AI Job Finder
Resume
   ↓
AI Analysis
   ↓
Your Profile
   ↓
Preferences
   ↓
Opportunity Matching
   ↓
Relevant Jobs & Internships
   ↓
Apply

✨ Features
📄 Resume Analysis
Upload your resume and let the system analyze your professional profile.

The platform can use information such as:
- Skills
- Education
- Experience
- Technical background
- Other relevant resume information
🤖 AI-Powered Understanding
AI is used to understand the information contained in your resume and assist with finding opportunities that are relevant to your profile.
🎯 Personalized Preferences
Tell the platform what you're looking for.

Depending on the available options, you can specify things such as:
- Desired role
- Job/internship preference
- Location
- Domain
- Other opportunity preferences
🔎 Opportunity Discovery
Discover jobs and internships based on your profile and preferences instead of manually searching through countless listings.
🧠 Profile-Based Matching
The platform combines information from your resume with your preferences to help surface more relevant opportunities.
💼 Opportunity Details
Explore opportunity information before deciding whether it is relevant to you.
🔗 Direct Application
When you find an opportunity you want to pursue, you can continue to the original listing/application page.

AI Job Finder does not replace the employer's application process.
👤 No Mandatory Login
The current MVP is designed to allow users to start using the platform without requiring a traditional account.
📱 Responsive Experience
The interface is designed to work across desktop and mobile screen sizes.
🧠 How It Works
                 ┌──────────────────┐
                 │   Upload Resume  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   AI Analysis    │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ Set Preferences  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ Search & Matching│
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  Opportunities   │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   Apply Directly │
                 └──────────────────┘

🏗️ Architecture
AI Job Finder uses a separated frontend/backend architecture.
                         USER
                           │
                           ▼
                 ┌─────────────────────┐
                 │  Netlify Frontend   │
                 │                     │
                 │ HTML / CSS / JS     │
                 └──────────┬──────────┘
                            │
                         HTTPS API
                            │
                            ▼
                 ┌─────────────────────┐
                 │  Railway Backend    │
                 │                     │
                 │ Python API          │
                 │ Resume Processing   │
                 │ AI Analysis         │
                 │ Job Search          │
                 │ Matching             │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ AI / Data Services  │
                 └─────────────────────┘

🛠️ Technology Stack
Frontend
- HTML5
- CSS3
- JavaScript
- Responsive Web Design
- Netlify
Backend
- Python
- REST-style API architecture
- Resume processing
- AI analysis
- Job discovery
- Opportunity matching
- Railway
Development
- Git
- GitHub
- Automated testing
- Environment-based configuration
📁 Project Structure
ai-job-finder/
│
├── frontend/
│   ├── assets/
│   ├── js/
│   ├── scripts/
│   ├── index.html
│   ├── dashboard.html
│   ├── onboarding.html
│   ├── opportunity.html
│   ├── profile.html
│   ├── settings.html
│   ├── privacy.html
│   ├── terms.html
│   └── config.js
│
├── backend/
│   ├── jobagent/
│   ├── app.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── Procfile
│   └── runtime.txt
│
├── tests/
│
├── netlify.toml
├── render.yaml
├── README.md
└── .gitignore

The project structure may evolve as new features are added.

🚀 Getting Started
Prerequisites
Make sure you have:
- Python 3.12+
- Git
- A modern web browser
- Node.js if required by the frontend tooling
1. Clone the Repository
git clone https://github.com/Rudra-113/ai-job-finder.git
cd ai-job-finder

2. Backend Setup
Move into the backend directory:
cd backend

Create a virtual environment.
Windows
python -m venv .venv
.venv\Scripts\activate

macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

Install dependencies:
pip install -r requirements.txt

3. Environment Configuration
Configure the required environment variables using the provided environment example files.

Never commit:
.env
API keys
Secret keys
Private credentials
Production tokens
User resumes
Personal user data

4. Start the Backend
From the backend/ directory:
python app.py

The backend will start using the application's configured host and port.
5. Run the Frontend
Serve the frontend/ directory using your preferred local static server.

Make sure the frontend API configuration points to your local backend during development.
🧪 Testing
The project contains automated tests covering important application functionality.

Run the test suite with:
pytest

Before submitting changes, make sure existing tests continue to pass.
🔐 Security & Privacy
AI Job Finder may process sensitive information contained in resumes.

The project therefore follows important security principles:
- API credentials remain on the backend
- Secrets are not exposed in frontend code
- CORS is configured for the application
- Host validation is enabled
- CSRF protection is used where applicable
- Anonymous visitors can be identified without requiring traditional login
- Uploaded files are processed through backend-controlled routes
- Private backend information should not be exposed publicly
⚠️ Never commit sensitive information
.env
API keys
Secret keys
Access tokens
Private credentials
User resumes
Personal information
Production configuration containing secrets

🌍 Live Application
🚀 Try AI Job Finder
Live Website:

https://sprightly-pudding-24dc69.netlify.app/

Backend Health Endpoint:

https://ai-job-finder-production-3898.up.railway.app/api/health
🗺️ Roadmap
✅ Phase 1 — MVP
- [x] Resume upload
- [x] Resume analysis
- [x] Preference collection
- [x] Opportunity discovery
- [x] Job matching
- [x] Job details
- [x] Direct application links
- [x] Anonymous user experience
- [x] Production deployment
- [x] Responsive interface
🔄 Phase 2 — Analytics & Administration
- [ ] Private admin dashboard
- [ ] Visitor analytics
- [ ] Resume upload analytics
- [ ] AI analysis analytics
- [ ] Search analytics
- [ ] Job view analytics
- [ ] Apply click analytics
- [ ] API error monitoring
- [ ] Resume/profile management
- [ ] Activity monitoring
🚀 Phase 3 — Personalization
- [ ] Improved recommendation engine
- [ ] Better resume-to-job matching
- [ ] Personalized opportunity ranking
- [ ] Saved opportunities
- [ ] Application tracking
- [ ] User preference history
- [ ] Personalized job alerts
💎 Phase 4 — Advanced Features
Potential future features:
- AI career recommendations
- Resume improvement suggestions
- Skill-gap analysis
- Career roadmaps
- Personalized job alerts
- Advanced matching
- Application tracking
- Career analytics
- Premium features
🔮 Future Vision
The long-term goal is to evolve AI Job Finder from a simple job discovery tool into an AI-powered career discovery platform.
                    YOUR RESUME
                         │
                         ▼
                ┌─────────────────┐
                │  AI CAREER      │
                │    ENGINE       │
                └────────┬────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
        JOBS       INTERNSHIPS        SKILLS
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                PERSONALIZED
                OPPORTUNITIES
                         │
                         ▼
                   APPLY / TRACK

The vision is to help students and professionals spend less time searching and more time building their careers.
🤝 Contributing
Contributions, suggestions, ideas, and improvements are welcome.
Create a feature branch
git checkout -b feature/your-feature

Before submitting changes
Please ensure:
- Existing functionality still works
- Tests pass
- No secrets are committed
- Changes are documented
- Unnecessary dependencies are avoided
- Security considerations are addressed
🐛 Issues & Feature Requests
Found a bug or have an idea?

Open an issue in the GitHub repository:

https://github.com/Rudra-113/ai-job-finder/issues

When reporting an issue, include:
- What happened
- What you expected
- Steps to reproduce
- Browser/environment information
- Relevant error messages
Please do not include private resumes, API keys, passwords, or other sensitive information.
👨‍💻 Author
Rudrapratap Mishra
Computer Science & Engineering Student
Lucknow, India
Interests
- Artificial Intelligence
- Full-Stack Development
- Software Engineering
- Developer Tools
- AI Applications
- Building practical products
📌 Project Status
🟢 Live — Active Development

AI Job Finder is currently available as a working MVP and is continuously being improved.
<p align="center">

🚀 Find opportunities. Build your future.
AI Job Finder
Built with ❤️ and AI
</p>
```
