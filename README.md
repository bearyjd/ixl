# ixl — IXL Student Account CLI

CLI scraper for IXL student accounts. Pulls SmartScores, trouble spots, usage stats, and diagnostic data. Designed to be called by an OpenClaw cron agent via `--json`.

## Setup

```bash
pip install -e .
pip install 'ixl[browser]'
playwright install chromium
```

Configure credentials (pick one):

```bash
# Option A: interactive
ixl init

# Option B: .env file
mkdir -p ~/.ixl && chmod 700 ~/.ixl
cat > ~/.ixl/.env << 'EOF'
IXL_EMAIL="username@schoolslug"
IXL_PASSWORD="your-password"
EOF
chmod 600 ~/.ixl/.env

# Option C: environment variables
export IXL_EMAIL="username@schoolslug"
export IXL_PASSWORD="your-password"
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `IXL_EMAIL` | yes | — | Username or username@school (e.g. `jdoe@myschool`) |
| `IXL_PASSWORD` | yes | — | IXL login password |
| `IXL_SCHOOL` | no | parsed from email | School slug (e.g. `myschool`) |

Config priority: env vars > `~/.ixl/.env`

## Usage

```
ixl init                                              # interactive credential setup
ixl children                    [--json]              # show student profile
ixl assigned    [--subject SUBJ] [--priority] [--json] # teacher-assigned skills remaining
ixl diagnostics                 [--json]              # diagnostic levels per subject
ixl skills      [--subject SUBJ] [--json]             # SmartScores per skill
ixl trouble                     [--json]              # trouble spots report
ixl usage       [--days N]      [--json]              # usage stats
ixl summary     [--child NAME] [--format FMT] [--no-save] [--json]  # everything in one shot
ixl compare                     [--json]              # side-by-side for all accounts.env children
ixl notify      [--dry-run]     [--json]              # send webhook notifications
ixl goals       [--init]        [--json]              # view or initialize weekly goals
ixl trends      [--days N]      [--json]              # progress over time (requires snapshots)
```

All commands accept `--json` for machine-readable output. Exit codes: **0** success/partial, **1** runtime failure, **2** setup error (missing config/credentials), **130** interrupted.

## Examples

```bash
# Human-readable summary
ixl summary

# How many assigned skills are left? (sorted by urgency)
ixl assigned --priority

# JSON dump (what the cron agent runs)
ixl summary --json

# Just math skills
ixl skills --subject math --json

# Usage over the last 30 days
ixl usage --days 30

# Compare all children side-by-side (reads ~/.ixl/accounts.env)
ixl compare --json

# Send webhook notification (dry run to preview)
ixl notify --dry-run

# Initialize weekly goals from recent usage
ixl goals --init

# View current goal status
ixl goals --json

# Progress trends over the last 14 days
ixl trends --days 14

# Export summary as CSV
ixl summary --format csv
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (ok or warning with partial data) |
| 1 | Runtime failure (scraping error, all deliveries failed) |
| 2 | Setup error (missing credentials, missing config file) |
| 130 | Interrupted (Ctrl-C) |

## JSON Output Contract

All `--json` output is wrapped in a status envelope:

```json
{
  "status": "ok",
  "warnings": [],
  "errors": [],
  "student": { "name": "...", "grade": "..." },
  "...": "data fields spread inline"
}
```

`status` is one of `"ok"`, `"warning"` (partial success), or `"error"`. Warnings are non-fatal; data may still be present. Errors indicate failure.

```json
{
  "status": "warning",
  "warnings": [
    {"code": "compare.account_failed", "message": "...", "stage": "compare", "retryable": true}
  ],
  "errors": [],
  "children": [...]
}
```

## AI Agent Integration (OpenClaw / ChatGPT / etc)

Add this to the agent's System Prompt or Tool Description:

```text
# IXL Data Access (via `ixl` CLI)

You have access to the `ixl` command-line tool to fetch a student's IXL practice data. ALWAYS use the `--json` flag so you can parse the output programmatically.

## Available Commands:

1. **How much is left? (Use this for daily check-ins)**
   `ixl assigned --json`
   - Shows teacher-assigned skills: how many done, in progress, and not started.
   - Returns `totals` per subject and a `remaining` list of incomplete skills.
   - This is the go-to command for "how much IXL do they have left?"

2. **The Full Briefing**
   `ixl summary --json`
   - Returns a complete overview in ~20 seconds.
   - Includes: student info, diagnostic levels, skill scores, trouble spots, and usage stats.

3. **Skill Progress**
   `ixl skills --json` or `ixl skills --subject math --json`
   - Every skill with SmartScore, questions answered, time spent, and last practiced date.
   - Each skill has a `suggested` boolean indicating if teacher-assigned.
   - Subjects: math, ela, spanish.

4. **Trouble Spots**
   `ixl trouble --json`
   - Skills where the student is struggling — sorted by number of missed questions.
   - Includes current SmartScore, skill code, and grade level.

5. **Usage Stats**
   `ixl usage --days 7 --json`
   - Time spent, questions answered, skills practiced, days active.
   - Includes per-session breakdowns with score changes per skill.
   - Adjust `--days` for different time windows (7, 14, 30).

6. **Diagnostics**
   `ixl diagnostics --json`
   - Diagnostic assessment scores per subject (if the student has taken them).

## JSON Structure Guide for `ixl assigned --json`:
- `totals`: {SubjectName: {assigned, done, in_progress, not_started, remaining}}
- `remaining`: [{id, name, smart_score, questions, skill_code, category, subject, suggested}]

## JSON Structure Guide for `ixl summary --json`:

All commands return a status envelope:
- `status`: "ok" | "warning" | "error"
- `warnings`: [{code, message, stage, retryable}] — non-fatal issues; data may still be present
- `errors`: [{code, message, stage, retryable}] — fatal issues

Data fields are spread inline alongside the envelope:
- `student`: {name, uid, grade}
- `timestamp`: When the data was fetched
- `diagnostics`: [{subject, overall_level, max_score, has_data, scores: []}]
- `skills`: [{subject, grade, mastered, excellent, skills: [{id, name, smart_score, time_spent_min, questions, last_practiced, skill_code}]}]
- `trouble_spots`: [{skill, name, skill_code, grade, missed_count, score}]
- `usage`: {period, time_spent_min, questions_answered, skills_practiced, days_active, sessions: [...], top_categories: [...]}
- `goals`: present when goals are configured — [{name, target, current, status, unit}]

## Exit Codes:
- 0 = success (ok or warning with partial data)
- 1 = runtime failure (scraping error, all webhook deliveries failed)
- 2 = setup error (missing credentials, missing config file)
- 130 = interrupted (Ctrl-C)

## SmartScore Scale:
- 0 = no practice
- 1-59 = practicing
- 60-79 = good progress
- 80-89 = excellent
- 90-100 = mastered

When summarizing for the user:
- Lead with how many assigned skills remain (from `ixl assigned`).
- Focus on trouble spots and skills with low SmartScores.
- Highlight recent progress (score changes in usage sessions).
- Note skills where the student went from 0 to mastered in one session (strong performance).
- Do not output raw JSON to the user; format it into a friendly, readable report.
```

## How it works

- Logs in via Playwright (headless Chromium) because Cloudflare blocks raw HTTP login
- After login, exports browser cookies to a `requests.Session` for all subsequent API calls
- Caches session per account at `~/.ixl/sessions/{sha256(email)[:12]}.json` (60-min TTL, auto-refreshes)
- Fetches data from IXL's internal JSON XHR endpoints (same ones the analytics SPA uses)
- All status/debug output goes to stderr; `--json` output is clean on stdout

## File layout

```
~/.ixl/
  .env                              # IXL_EMAIL, IXL_PASSWORD (0600)
  accounts.env                      # multi-child: name:email:password, one per line (0600)
  sessions/{sha256(email)[:12]}.json  # per-account session cache (0600, auto-managed)
  snapshots/                        # trend data written by ixl summary (auto-managed)
  notifications.json                # webhook configs for ixl notify
  goals.json                        # weekly goal targets (generated by ixl goals --init)
```

## Cron (Multiple Students)

Each student has their own IXL login. The included cron script scrapes all accounts in one shot.

### 1. Create accounts file

```bash
cp cron/accounts.env.example ~/.ixl/accounts.env
chmod 600 ~/.ixl/accounts.env
```

Edit `~/.ixl/accounts.env` — one line per student:

```
child1:jdoe@myschool:secretpass
child2:jsmith@myschool:secretpass
```

### 2. Test it

```bash
./cron/ixl-cron.sh
ls /tmp/ixl/
# child1-summary.json  child1-assigned.json  child2-summary.json  child2-assigned.json
```

### 3. Add to crontab

```bash
# Daily at 6am — scrape all students
0 6 * * * /path/to/ixl-scrape/cron/ixl-cron.sh 2>/tmp/ixl-cron.log

# Custom output directory
0 6 * * * OUTPUT_DIR=/data/ixl /path/to/ixl-scrape/cron/ixl-cron.sh 2>/tmp/ixl-cron.log
```

### Single student (ad-hoc)

```bash
IXL_EMAIL="jdoe@myschool" IXL_PASSWORD="pass" ixl assigned --json
```

## OpenClaw Skill

Use `ixl` as an OpenClaw agent skill for automated daily reports via Signal.

### 1. Add the agent

Copy the agent definition from `openclaw-agent.yaml` into your OpenClaw `agents.yaml`:

```bash
cat openclaw-agent.yaml >> ~/.openclaw/agents.yaml
```

### 2. Install on LXC / remote server

```bash
ssh root@<LXC_IP> 'bash -s' < install-lxc.sh
```

This installs system deps, the `ixl` CLI, Playwright + Chromium, and clones the repo for the cron script. Idempotent — safe to re-run.

After install, create `~/.ixl/accounts.env` and `~/.ixl/.env` on the server (see "Cron (Multiple Students)" section above).

### 4. Create schedule in OpenClaw app

- **Name:** IXL Daily Report
- **Cron:** `0 6 * * *` (daily at 6am)
- **Prompt:** "Run the daily IXL report for all kids and send it to me via Signal."

The agent uses Haiku model (`anthropic/claude-3-5-haiku-20241022`) for cost-effective formatting (~$0.001 per report).
