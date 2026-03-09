# ixl — IXL Parent Portal CLI Scraper

CLI scraper for the IXL parent portal. Pulls diagnostic scores, skill progress, trouble spots, and usage stats for all linked children. Designed to be called by an OpenClaw cron agent via `--json`.

Mirrors the architecture of [`sgy`](https://github.com/bearyjd/sgy) — same conventions, same consumer (OpenClaw), different data source.

---

## Why

Schoology gives us assignments/grades/announcements. IXL gives us the _practice_ side — what skills they're working on, where they're struggling, diagnostic grade-level scores. Together they're the full picture.

---

## Architecture

```
ixl-scrape/
├── pyproject.toml          # "ixl" package, entry point ixl_cli.cli:main
├── ixl_cli/
│   ├── __init__.py
│   ├── __main__.py          # python -m ixl_cli
│   ├── cli.py               # argparse + commands
│   ├── session.py           # login, session cache, request wrapper
│   └── scrapers/
│       ├── __init__.py
│       ├── children.py      # child discovery
│       ├── diagnostics.py   # diagnostic scores per subject/strand
│       ├── skills.py        # skill-level progress & SmartScores
│       ├── trouble_spots.py # trouble spots report
│       └── usage.py         # time spent, questions answered
├── .env.example
├── .gitignore
├── LICENSE                  # MIT
└── README.md
```

Split scrapers into modules (unlike `sgy` which is one file) because IXL has more distinct data domains and the analytics pages are likely separate AJAX endpoints.

---

## Phase 0: Recon (Do This First)

Before writing any scraping code, reverse-engineer the IXL parent portal in the browser. This is the most important phase — `sgy` took multiple iterations to find the right endpoints.

### What to capture (DevTools Network tab, logged in as parent):

1. **Login flow**
   - `POST /signin/ajax/page` — what fields? CSRF token location?
   - What cookies get set? Names, domains, expiry
   - Does `rememberUser=true` extend session TTL?

2. **Parent dashboard load**
   - Hit `/analytics` — what XHR/fetch calls fire?
   - Look for JSON endpoints (these are gold — way easier than HTML parsing)
   - Check for `window.__INITIAL_STATE__` or similar JS-embedded data blobs

3. **Child switching**
   - If multi-child, how does the UI switch? Query param? Cookie? POST?
   - Watch the network tab when switching children

4. **Report pages**
   - `/analytics` subsections — what are the actual URLs?
   - Each report page: does it load data via AJAX or server-render?
   - Look for patterns like `/api/`, `/ajax/`, or `?format=json`

5. **Anti-bot**
   - Is reCAPTCHA v3 active on login? (research says available but currently disabled)
   - Any Cloudflare/WAF challenge pages?
   - Rate limit headers? (`X-RateLimit-*`, `Retry-After`)

### Capture template (save as `NOTES.md`):

```markdown
# IXL Scraper - Recon Notes

## Login
- POST URL:
- Form fields:
- CSRF token source:
- Session cookie names:
- Session TTL (observed):

## Child Discovery
- Endpoint/method:
- Response format:

## Analytics Endpoints Found
| Page | URL | Method | Returns |
|------|-----|--------|---------|
| Dashboard | | | |
| Diagnostics | | | |
| Trouble Spots | | | |
| Usage | | | |

## Anti-Bot Observations
- reCAPTCHA active: yes/no
- Rate limiting observed: yes/no
- JS-required pages:
```

---

## Phase 1: Auth & Session Management

### Config

Follow `sgy` conventions exactly:

```
~/.ixl/
  .env              # IXL_EMAIL, IXL_PASSWORD (0600)
  session.json      # cached session cookies (0600, auto-managed)
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IXL_EMAIL` | yes | — | IXL parent account email |
| `IXL_PASSWORD` | yes | — | IXL parent account password |

Config priority: env vars > `~/.ixl/.env`

### Login implementation

```python
# Pseudocode — actual fields TBD from recon
class IXLSession:
    def __init__(self, verbose=True):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = REALISTIC_UA

    def _do_login(self):
        # 1. GET /signin — extract CSRF token
        # 2. POST /signin/ajax/page with email, password, csrf
        # 3. Verify: follow redirect or check response JSON
        # 4. Cache cookies to ~/.ixl/session.json
        pass
```

### Session caching

Same pattern as `sgy`:
- Save cookies + timestamp to `session.json`
- TTL TBD from recon (start with 60 min, adjust)
- On load: restore cookies, verify with a lightweight GET, re-auth if stale

### Rate limiting

- 1-3 second jitter between requests (IXL is pickier than Schoology)
- Exponential backoff on 429
- Max 3 retries

---

## Phase 2: Child Discovery

IXL parent accounts link to one or more student accounts. Need to find:
- How to list linked children (likely in dashboard page or an API call)
- Child identifiers (user ID, name)
- How to switch context to view a specific child's data

**Expected output:**
```json
[
  {"name": "Alex Smith", "uid": "12345678", "grade": "4"}
]
```

---

## Phase 3: Scrapers

### 3a. Diagnostics

IXL Real-Time Diagnostic gives strand-level grade equivalency scores for Math and ELA.

**Target data:**
```json
{
  "subject": "Math",
  "overall_level": "4.5",
  "strands": [
    {"name": "Algebra and Algebraic Thinking", "level": "5.2", "growth": "+0.3"},
    {"name": "Geometry", "level": "3.8", "growth": "-0.1"}
  ],
  "last_assessed": "2026-03-07"
}
```

### 3b. Skill Progress

SmartScores per skill practiced. IXL's scoring: 0-100, 80+ = mastery.

**Target data:**
```json
{
  "subject": "Math",
  "grade": "4",
  "skills": [
    {"id": "M.1", "name": "Add two numbers up to four digits", "smart_score": 92, "time_spent_min": 12, "questions": 25},
    {"id": "M.2", "name": "Subtract two numbers up to four digits", "smart_score": 67, "time_spent_min": 8, "questions": 18}
  ]
}
```

### 3c. Trouble Spots

IXL pinpoints specific concepts a child is struggling with, including example missed questions.

**Target data:**
```json
{
  "trouble_spots": [
    {"skill": "M.14", "name": "Multiply by 7", "missed_count": 8, "last_attempted": "2026-03-06"}
  ]
}
```

### 3d. Usage Stats

Time on task, questions answered, days active.

**Target data:**
```json
{
  "period": "last_7_days",
  "time_spent_min": 45,
  "questions_answered": 187,
  "skills_practiced": 12,
  "days_active": 4
}
```

---

## Phase 4: CLI

```
ixl init                                    # set up credentials interactively
ixl children                                # list linked children
ixl diagnostics [--child NAME] [--json]     # diagnostic levels per subject
ixl skills      [--child NAME] [--subject SUBJ] [--json]  # skill scores
ixl trouble     [--child NAME] [--json]     # trouble spots
ixl usage       [--child NAME] [--days N] [--json]         # usage stats
ixl summary     [--child NAME] [--json]     # everything in one shot
```

All commands accept `--json` for machine-readable output. `--child` takes a first-name substring match. Stderr for status/debug, stdout for data.

---

## Phase 5: AI Agent Integration

Same pattern as `sgy`. System prompt snippet for OpenClaw:

```text
# IXL Data Access (via `ixl` CLI)

You have access to the `ixl` command-line tool to fetch the user's children's IXL practice data. ALWAYS use the `--json` flag.

## Available Commands:

1. **Daily Overview**
   `ixl summary --json`
   - Diagnostic levels, recent skill progress, trouble spots, usage — all children.

2. **Diagnostic Deep-Dive**
   `ixl diagnostics --child <FirstName> --json`
   - Strand-level diagnostic scores and growth for Math + ELA.

3. **Skill Progress**
   `ixl skills --child <FirstName> --subject math --json`
   - Per-skill SmartScores. 80+ = mastered, <60 = needs work.

4. **Trouble Spots**
   `ixl trouble --child <FirstName> --json`
   - Specific concepts the child is struggling with.

When summarizing:
- Highlight trouble spots and skills below 60 SmartScore.
- Compare diagnostic levels to actual grade level (e.g., "4th grader reading at 5.2 level").
- Don't dump raw JSON — make it a readable briefing.
```

---

## Tech Stack

- **Python >=3.10** (match `sgy`)
- **requests** — HTTP session management
- **beautifulsoup4** — HTML parsing (fallback if no JSON endpoints)
- **Possibly playwright** — only if recon reveals JS-required pages that have no AJAX fallback. Avoid if possible (heavyweight dependency for a CLI tool).

### pyproject.toml skeleton

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "ixl"
version = "0.1.0"
description = "IXL parent portal CLI scraper"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.10"
dependencies = [
    "requests>=2.28",
    "beautifulsoup4>=4.12",
]

[project.scripts]
ixl = "ixl_cli.cli:main"
```

---

## Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| reCAPTCHA v3 enabled on login | Medium | Fall back to browser-based cookie export tool (`ixl auth-import`) |
| Analytics pages are pure SPA (no AJAX JSON) | Medium | Playwright for initial recon; try to find underlying API calls |
| IXL changes HTML structure | High (long-term) | Same as `sgy` — fragile by nature, keep selectors documented |
| Rate limiting / IP blocking | Medium | Conservative delays, session caching, don't hammer |
| Multi-child switching is complex | Low | Recon will reveal mechanism; worst case it's just separate logins |

---

## Implementation Order

1. **Recon** — browser DevTools, map endpoints, fill out NOTES.md
2. **Auth + session** — login, cache, verify
3. **Children** — list + switch
4. **Diagnostics** — highest-value data, simplest structure
5. **Skills** — bulk data, may need pagination
6. **Trouble spots** — targeted report
7. **Usage** — stats aggregation
8. **Summary command** — combine all
9. **README + agent prompt** — docs for humans and AI
10. **Cron integration** — `0 6 * * * ixl summary --json > /tmp/ixl-daily.json`

---

## Cron (End State)

```bash
# Daily at 6:05am — 5 min after sgy to stagger
5 6 * * * /usr/local/bin/ixl summary --json > /tmp/ixl-daily.json 2>/dev/null
```

OpenClaw agent reads both `/tmp/schoology-daily.json` and `/tmp/ixl-daily.json` for the morning briefing.
