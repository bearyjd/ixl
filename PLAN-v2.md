# IXL Scraper v0.3 — Bug Fixes & Feature Plan

**Date:** 2026-03-30
**Current version:** 0.2.0
**Target version:** 0.3.0

---

## Part 1: Bug Fixes (Priority Order)

### CRITICAL

#### 1. Hardcoded school-year start date — silent time bomb
**Files:** `scrapers/skills.py:136`, `scrapers/children.py:59`
**Problem:** `start_str = "2025-08-01"` will cause the tool to return empty data after August 2026 with no error message.
**Fix:** Compute dynamically:
```python
today = date.today()
school_year_start = date(today.year, 8, 1) if today.month >= 8 else date(today.year - 1, 8, 1)
start_str = school_year_start.isoformat()
```

#### 2. Cron script produces corrupt JSON on partial failure
**File:** `cron/ixl-cron.sh:34`
**Problem:** `2>/dev/null` suppresses all errors. If a command fails mid-output, the JSON file is truncated/invalid and overwrites the last good file.
**Fix:** Write to a temp file, validate JSON, then atomically move into place. Log errors to a `.log` file instead of `/dev/null`.

#### 3. Credentials leaked in git history
**File:** Git commit `b3b0133`
**Problem:** Real student credentials (3 accounts) are permanently in git history even though commit `40ba5c1` sanitized the files.
**Action:** Rotate all three passwords immediately. Rewrite git history with `git-filter-repo` or BFG Repo-Cleaner before any public push.

### HIGH

#### 4. Password visible during `ixl init`
**File:** `cli.py:287`
**Problem:** `input()` echoes password to terminal.
**Fix:** Use `getpass.getpass("IXL Password: ")`.

#### 5. Rate-limit exhaustion returns silent empty data
**File:** `session.py:200-202`
**Problem:** After 3 retries on HTTP 429, `_request` returns the 429 response. `fetch_json` sees non-200 and returns `None`. Callers show "No data found" — user has no idea they're rate-limited.
**Fix:** Raise `requests.exceptions.HTTPError` when retries exhausted on 429.

#### 6. `UnboundLocalError` on login failure path
**File:** `session.py:322`
**Problem:** If Playwright fails between `page.click` and `cookie_dict` assignment, the variable is never defined. The `if not cookie_dict:` check crashes with `UnboundLocalError`.
**Fix:** Initialize `cookie_dict = {}` and `cookie_domains = {}` before the `try` block.

#### 7. `.env` file injection with special characters in password
**File:** `cli.py:295-298`
**Problem:** Passwords containing `"`, `\`, `$`, or newlines produce malformed `.env` files.
**Fix:** Escape special characters before writing, or switch to JSON format for credential storage.

#### 8. Monkey-patching session object for grade cache
**File:** `scrapers/skills.py:32,52`
**Problem:** `setattr(session, cache_key, active)` pollutes the session namespace. Fragile and untestable.
**Fix:** Add `self._cache: dict = {}` to `IXLSession.__init__` and use it properly.

### MEDIUM

#### 9. Cron script breaks on passwords containing colons
**File:** `cron/ixl-cron.sh:28`
**Problem:** `IFS=: read -r name email password` splits on ALL colons. Password `p@ss:word` gets truncated.
**Fix:** Parse with parameter expansion: extract first two fields by `:`, rest is password.

#### 10. TOCTOU race on credential/session file creation
**Files:** `session.py:132-137`, `cli.py:294-299`
**Problem:** File created with default permissions, then `chmod` applied — brief window where file is world-readable.
**Fix:** Use `os.open()` with explicit mode `0o600` for atomic permission setting.

#### 11. Cron output to world-readable `/tmp/ixl/`
**File:** `cron/ixl-cron.sh:17`
**Problem:** Student PII (names, grades, scores) written to `/tmp/ixl/` with default permissions.
**Fix:** Default to `~/.ixl/output/` with `chmod 700`.

#### 12. `int()` cast on grade can crash on "K" or "PK"
**File:** `scrapers/skills.py:150`
**Problem:** Kindergarten students return `"K"` for grade, causing `ValueError`.
**Fix:** Wrap in try/except, default to grade 0 for K/PK.

#### 13. Inconsistent error contracts between `fetch_json` and `fetch_page`
**File:** `session.py:344-358`
**Problem:** `fetch_page` raises on error, `fetch_json` silently returns `None`.
**Fix:** Make both raise, handle at caller level.

#### 14. No session file locking — concurrent runs corrupt `session.json`
**File:** `session.py:132-137`
**Problem:** Overlapping CLI invocations can corrupt the session file mid-write.
**Fix:** Atomic write (temp file + `os.rename`).

### LOW

#### 15. Redundant `import time as _time` inside `_do_login`
**File:** `session.py:286`
**Fix:** Remove inline import, use module-level `time`.

#### 16. Bump `requests` minimum to `>=2.33.0`
**File:** `pyproject.toml:12`
**Fix:** Update dependency version to address CVE-2026-25645.

---

## Part 2: Feature Plan

### Feature 1: Historical Trend Tracking
**Priority:** High
**Effort:** Medium

**What:** Store daily snapshots of SmartScores, diagnostic levels, and usage stats locally so the tool can show progress over time.

**Why:** Currently each run is stateless — you only see today's data. Parents and the OpenClaw agent have no way to answer "is my kid improving?" without manually comparing JSON files.

**Implementation:**
- Add `~/.ixl/history/` directory with date-stamped JSON files (`2026-03-30.json`)
- New CLI command: `ixl trends [--days 30] [--subject math] [--json]`
- Show: SmartScore deltas, diagnostic level changes, usage trends (time/questions per week)
- Human output: sparkline-style ASCII charts or simple `+3 ↑` / `-2 ↓` indicators
- JSON output: array of `{date, metric, value}` for agent consumption
- Auto-save snapshot on every `ixl summary` run (opt-out with `--no-save`)
- Retention: keep 90 days by default, configurable

**New files:**
- `ixl_cli/history.py` — save/load/query logic
- Update `cli.py` with `trends` subcommand

---

### Feature 2: Goal Tracking & Alerts
**Priority:** High
**Effort:** Low

**What:** Let parents set daily/weekly targets and get alerts when kids are behind or ahead.

**Why:** The OpenClaw agent currently reports raw numbers. Parents want to know "did they do enough today?" without mental math.

**Implementation:**
- Config in `~/.ixl/goals.yaml`:
  ```yaml
  daily:
    time_min: 30          # minutes per day
    questions: 50         # questions per day
  weekly:
    skills_mastered: 3    # new 90+ scores per week
    days_active: 5        # days with any practice
  ```
- New CLI command: `ixl goals [--json]` — shows progress vs targets
- `ixl summary` gains a `goals` section in output when goals are configured
- Traffic-light status: on-track / behind / ahead
- JSON output includes `goal_status` field for agent consumption

**New files:**
- `ixl_cli/goals.py` — config loading and evaluation
- `~/.ixl/goals.yaml` — user config (created by `ixl goals --init`)

---

### Feature 3: Multi-Account Session Isolation
**Priority:** High
**Effort:** Low

**What:** Per-account session caching instead of a shared `session.json`.

**Why:** Current design uses one `~/.ixl/session.json` for all accounts. The cron script runs multiple accounts sequentially, each overwriting the previous session. This causes unnecessary re-logins and risks corruption on concurrent runs.

**Implementation:**
- Session file keyed by username hash: `~/.ixl/sessions/{sha256(email)[:12]}.json`
- `IXLSession` resolves session path from configured email
- Backward compatible: migrate existing `session.json` on first run
- Atomic writes via temp file + `os.rename`

**Modified files:**
- `session.py` — session path resolution, atomic writes

---

### Feature 4: Assigned Work Focus Mode
**Priority:** Medium
**Effort:** Low

**What:** Dedicated view showing only incomplete teacher-assigned work, sorted by urgency.

**Why:** `ixl assigned` exists but doesn't prioritize. Parents need "what should my kid work on right now?" with smart ordering.

**Implementation:**
- `ixl assigned --priority [--json]` flag
- Sorting logic: due-date (if available) > in-progress first > lowest SmartScore > most questions remaining
- Group by subject with completion percentage bars in human output
- Add `priority_rank` field to JSON output
- Add `--subject` filter (already exists, just verify it works with priority)

**Modified files:**
- `scrapers/skills.py` — priority scoring logic
- `cli.py` — updated output formatter

---

### Feature 5: Comparative Reports (Sibling View)
**Priority:** Medium
**Effort:** Medium

**What:** Side-by-side comparison across multiple student accounts.

**Why:** The cron script already handles multiple accounts, but there's no unified view. Parents with multiple kids want one report, not N separate ones.

**Implementation:**
- New CLI command: `ixl compare [--json]`
- Reads `~/.ixl/accounts.env` to discover all accounts
- Runs `summary` for each account, then merges into a comparison table
- Human output: side-by-side columns per child
- Highlights: who practiced more, who's struggling, who's ahead of grade level
- JSON output: `{children: [{name, summary}, ...], comparisons: {metric, values}}`

**New files:**
- `ixl_cli/compare.py` — multi-account aggregation
- Update `cli.py` with `compare` subcommand

---

### Feature 6: Webhook / Notification Support
**Priority:** Medium
**Effort:** Medium

**What:** Send alerts directly from the CLI without requiring the OpenClaw agent layer.

**Why:** Not everyone runs OpenClaw. Simple webhook support lets the cron script push notifications to Signal/Slack/Discord/email directly.

**Implementation:**
- Config in `~/.ixl/notifications.yaml`:
  ```yaml
  webhooks:
    - url: https://hooks.slack.com/services/...
      events: [daily_summary, goal_missed]
    - url: signal-cli://+1234567890
      events: [goal_missed]
  ```
- New CLI command: `ixl notify [--dry-run]` — sends configured notifications
- Built-in formatters: Slack blocks, Discord embeds, plain text
- Signal integration via `signal-cli` subprocess (already used by OpenClaw)
- Cron script updated to call `ixl notify` after scraping

**New files:**
- `ixl_cli/notify.py` — webhook dispatch
- Update `cron/ixl-cron.sh`

---

### Feature 7: Offline / Export Mode
**Priority:** Low
**Effort:** Low

**What:** Export data to CSV/HTML for sharing with teachers or offline review.

**Why:** Parents sometimes need to share IXL progress with tutors or in parent-teacher conferences. JSON isn't human-friendly, and the CLI output isn't shareable.

**Implementation:**
- `ixl summary --format csv > report.csv`
- `ixl summary --format html > report.html` (self-contained single-file HTML with inline CSS)
- HTML report: styled table with color-coded SmartScores, diagnostic charts via inline SVG
- CSV: flat table suitable for Google Sheets import

**Modified files:**
- `cli.py` — `--format` flag (json|csv|html), output routing
- New: `ixl_cli/export.py` — CSV/HTML renderers

---

### Feature 8: Test Suite
**Priority:** High
**Effort:** Medium

**What:** Automated tests for all scrapers and CLI commands.

**Why:** Zero tests currently. Every change risks breaking production daily reports with no safety net. The code review found multiple edge cases that tests would catch.

**Implementation:**
- `tests/` directory with pytest
- Unit tests for each scraper module using recorded API responses (fixtures)
- Integration tests for CLI commands (argparse wiring, output formatting)
- Session mock for testing without real IXL credentials
- CI: GitHub Actions workflow running tests on push
- Record fixtures: `ixl summary --json` output saved as test data (sanitized)

**New files:**
- `tests/conftest.py` — shared fixtures, mock session
- `tests/test_skills.py`, `test_diagnostics.py`, `test_trouble_spots.py`, `test_usage.py`, `test_children.py`
- `tests/test_cli.py` — CLI integration tests
- `tests/fixtures/` — recorded API responses
- `.github/workflows/test.yml` — CI config

---

## Implementation Roadmap

### Phase 1: Stabilize (v0.2.1) — Bug fixes only
1. Fix hardcoded school-year date (Critical #1)
2. Fix cron script JSON corruption (Critical #2)
3. Rotate leaked credentials (Critical #3)
4. Fix password echo, 429 handling, UnboundLocalError (#4-6)
5. Fix .env injection, grade "K" crash (#7, #12)
6. Fix cron colon parsing, TOCTOU, output permissions (#9-11)
7. Remaining low-priority fixes (#13-16)

### Phase 2: Foundation (v0.2.2)
1. Multi-account session isolation (Feature 3)
2. Test suite (Feature 8)
3. Atomic file writes throughout

### Phase 3: Features (v0.3.0)
1. Historical trend tracking (Feature 1)
2. Goal tracking & alerts (Feature 2)
3. Assigned work priority mode (Feature 4)

### Phase 4: Polish (v0.4.0)
1. Comparative reports (Feature 5)
2. Webhook notifications (Feature 6)
3. Export mode (Feature 7)
