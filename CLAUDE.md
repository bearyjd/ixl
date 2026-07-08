# CLAUDE.md — ixl-scrape

This file provides guidance to Claude Code (and other AI coding agents) when
working with code in this repository. It sits below the parent
`/home/user/Documents/vibe-code/school/CLAUDE.md`, which covers all three
sibling scrapers — read that first for cross-repo context (install/run
matrix, cron layout, credential file table). This file is ixl-scrape-specific
and goes deeper on things an agent needs to *act* on: verified commands, the
login/session/TTL model, the multi-account pattern's sharp edges, and known
structural obstacles.

No student data (names, scores, credentials) is or should ever be recorded
in this file — see the "Privacy" section at the bottom.

## Verified commands

These were confirmed against `Makefile`, `pyproject.toml`, and
`.github/workflows/ci.yml` in this repo — do not invent alternatives.

```bash
# Install (from repo root)
pip install -e ".[dev]"                 # dev = pytest>=7.0 (pyproject.toml)
pip install -e ".[browser]"              # browser = playwright>=1.40, only needed for login
playwright install chromium

# Tests
pytest                                   # all tests (or: python3 -m pytest, or: make test)
pytest tests/test_skills.py              # single file
pytest -k "test_name"                    # single test
pytest -v                                # verbose
pytest --tb=short -q                     # exactly what CI runs (.github/workflows/ci.yml)

# Lint
ruff check ixl_cli/                      # make lint
ruff check .                             # what CI actually runs (covers tests/ too)

# Git hooks (auto version bump on feat:/fix: commits)
make setup                               # sets core.hooksPath to .githooks, chmods hook + bump script
```

CI (`.github/workflows/ci.yml`) runs on Python 3.10 and 3.12, on push/PR to
`main`: install `-e ".[dev]"`, `ruff check .`, `pytest --tb=short -q`. There
is no separate coverage gate configured in CI — `pytest-cov` is not a
dependency here, so "80%+ coverage" per the global testing rule is aspirational
for this repo, not CI-enforced. If asked to raise coverage, add
`pytest-cov` to `dev` extras and wire `--cov=ixl_cli` into CI rather than
assuming it already runs.

**Verified during this audit (2026-07-07):** `python3 -m pytest -q --tb=short`
on a host with the `playwright` package installed but **no Chromium browser
binary downloaded** produced `1 failed, 123 passed` —
`tests/test_session.py::TestLoginFailure::test_login_failure_before_cookies_gives_runtime_error`
fails with a real `BrowserType.launch: Executable doesn't exist` error. This
is a pre-existing test bug (the test's `patch("ixl_cli.session.sync_playwright", ...)`
doesn't actually intercept the call, because `_do_login()` imports
`sync_playwright` with a function-local `import`, not a module-level one —
see `.agent_native/agent_roadmap.md` for the full root-cause and fix). If you
see this failure, it is **not** a regression you introduced — it is a
latent gap in the existing suite's Playwright mocking. Do not "fix" it by
installing Chromium as a workaround; fix the patch target instead.

Current package version per `pyproject.toml` is `0.16.5` (the parent
`school/CLAUDE.md` says `v0.2.0` — that's stale; trust `pyproject.toml`).

## Architecture recap (see parent CLAUDE.md for the full module table)

```
ixl_cli/
  session.py          # Playwright login, cookie export, per-account session cache, rate-limited request wrapper
  cli.py               # argparse + all commands (cmd_* functions), JSON envelope (make_result/add_warning/add_error)
  compare.py           # load_accounts() + build_comparison(); cmd_compare() itself lives in cli.py
  goals.py, history.py, notify.py, export.py
  scrapers/
    children.py, diagnostics.py, skills.py, trouble_spots.py, usage.py
```

## Login / session / TTL model — where it can silently break

`ixl_cli/session.py::IXLSession._do_login()` drives a headless Chromium
(Playwright) through the real IXL sign-in flow because **Cloudflare blocks
direct `requests` POSTs** to the login endpoint (confirmed in `NOTES.md`: raw
POST gets a silently-dropped body / generic error). The flow:

1. `page.goto(signin_url)` → `/signin/{school}` or `/signin`.
2. `page.wait_for_selector("#siusername")`, fill `#siusername` / `#sipassword`.
3. `page.click("#custom-signin-button")`.
4. `page.wait_for_url("**/dashboard**")` — success signal.
5. Visit `/analytics/score-grid` to warm up report cookies, `time.sleep(2)`.
6. Export **all** `ixl.com`-domain cookies from the Playwright browser context into `self.s` (a `requests.Session`), preserving each cookie's original `domain`.
7. `save_session({"cookies": ..., "domains": ...}, path=self._session_path)`.

**Chokepoints an agent should know about, in order of how silently they fail:**

- **Selector drift.** `#siusername`, `#sipassword`, `#custom-signin-button`,
  the `**/dashboard**` redirect target, and the error-detection selectors
  (`.error-message, .signin-error, #signin-error`) are all hard IXL-DOM
  dependencies. `NOTES.md` documents them in prose but **there is no HTML
  fixture anywhere in the repo** to regression-test against — see
  `.agent_native/agent_roadmap.md` item 1 for the concrete fix. Until that
  exists, a selector rename on IXL's side will only surface as a production
  timeout/`RuntimeError` from `_do_login()`, not a local test failure.
- **Cloudflare/anti-bot changes.** `NOTES.md`'s "Anti-Bot Observations"
  section is a point-in-time recon snapshot (reCAPTCHA Enterprise threshold
  0.0 / effectively disabled, `__cf_bm` cookie blocks raw POST but not
  Playwright). If Cloudflare tightens its bot-management policy, Playwright
  itself may start getting challenged — nothing in this codebase detects or
  retries a Cloudflare challenge page distinctly from a normal login failure;
  it will just show up as `page.wait_for_url` timing out and being reported
  as a generic "Login failed" `RuntimeError`.
- **TTL cache.** `SESSION_TTL = 60 * 60` (60 min, conservative — `NOTES.md`
  notes the real TTL is "unknown"). Cache key is
  `~/.ixl/sessions/{sha256(email)[:12]}.json`, one file per distinct
  `IXL_EMAIL` value (see `_session_path_for`). `ensure_logged_in()` tries the
  cached cookies with a live `GET /analytics/student-summary-practice` probe
  before trusting the TTL — so a *revoked-but-not-yet-expired* session (e.g.
  IXL invalidates it server-side before the 60-minute local TTL elapses) is
  caught by that probe request, not purely by the timestamp. A **stale
  session that still returns 200** on that probe endpoint but fails on other
  endpoints would not be detected until the failing endpoint is actually
  called — `ensure_logged_in()` only exercises one endpoint as its liveness
  check.
- **Legacy-session migration.** `load_session()` will copy the old shared
  `~/.ixl/session.json` into the new per-account path if the per-account file
  doesn't exist yet (`tests/test_session.py::TestSessionMigration` covers
  this). This is a one-time, one-directional migration — there's no code
  path that keeps the legacy file in sync afterward, which is fine as long
  as nothing else in the codebase still reads `SESSION_PATH` directly for a
  multi-account setup (it doesn't, as of this audit).

## Multi-account (`accounts.env`) pattern — documented, but has a real sharp edge

`~/.ixl/accounts.env` format: `name:username@school:password`, one line per
child (`ixl_cli/compare.py::load_accounts()` parses with `split(":", 2)` so
passwords containing colons are preserved). This *is* documented in
`README.md` ("Cron (Multiple Students)" section) and the parent
`school/CLAUDE.md`.

**Two different implementations of the "switch accounts" idea exist, with
different safety properties — do not conflate them:**

1. **`cron/ixl-cron.sh`** (shell): scopes credentials with an inline env
   prefix per invocation — `IXL_EMAIL="$email" IXL_PASSWORD="$password" ixl summary --json`.
   Each account gets a **fresh `ixl` process**; there is no shared mutable
   state between accounts. This is safe.
2. **`cmd_compare()` in `ixl_cli/cli.py`** (Python, used by `ixl compare`):
   loops over `load_accounts()` and does
   `os.environ["IXL_EMAIL"] = acct["email"]` / `os.environ["IXL_PASSWORD"] = ...`
   **in-place, in a single process**, then constructs a fresh `IXLSession()`
   (which re-reads `os.environ` via `load_config()`) for each account. A
   per-account failure is caught (`except Exception`), logged as a
   `compare.account_failed` warning, and the loop continues — so one
   account's exception does *not* stop later accounts from being scraped.
   However: **the original env vars are never restored after the loop**,
   success or failure. For the CLI entry point this doesn't matter (process
   exits), but it means `cmd_compare()` is not safe to call twice in the same
   long-lived process, or to call and then rely on `IXL_EMAIL`/`IXL_PASSWORD`
   reflecting whatever they were before the call. See
   `.agent_native/agent_roadmap.md` item 3 for the fix and the fact that
   `tests/test_compare.py` currently only tests `load_accounts()` and
   `build_comparison()` in isolation — the loop/env-mutation behavior itself
   is untested.

## Subject codes and SmartScore bands (reference only — no student data)

```
SUBJECT_IDS = {"math": 0, "ela": 1, "science": 2, "social_studies": 3, "spanish": 5}
ALL_SUBJECTS = "0,1,5"   # math, ela, spanish — the common student set
```

SmartScore bands (per `ixl_cli/session.py` docstring and `NOTES.md`):

| Range | Meaning |
|---|---|
| 0 | no practice |
| 1-59 | practicing / struggling |
| 60-79 | good progress |
| 80-89 | excellent |
| 90-100 | mastered |

`ixl assigned` filters skills where `suggested=true` (i.e. `isSkillSuggested`
from the API, meaning teacher-assigned rather than student-initiated).

## Test suite conventions (follow these when adding tests)

- Use the `mock_session` fixture (`tests/conftest.py`) for anything that
  needs an authenticated `IXLSession` without touching Playwright or real
  credentials — it patches `IXLSession.__init__` to a no-op and hand-builds
  the instance with `_logged_in=True`.
- Use `make_response(status_code, json_data=None, text="")` to build mock
  `requests.Response` objects; it wires up `raise_for_status()` to actually
  raise on 4xx/5xx like the real method.
- Use `tmp_ixl_dir` (a `tmp_path`-backed `~/.ixl` substitute) for anything
  touching file I/O under `~/.ixl/*` — never point tests at the real
  `~/.ixl` directory.
- Tests are organized as regression tests per numbered bug (`test_session.py`
  has `TestLoginFailure` / `TestFetchJsonErrorContract` / `TestAtomicSessionWrite`
  / `TestRateLimitExhaustion`, each docstring-tagged `"""Bug #N: ..."""`).
  Follow this convention for new bug-fix tests — it makes `git blame`/`grep
  "Bug #"` an effective way to find why a given test exists.
- **Known gap (see `.agent_native/agent_roadmap.md` for full detail):** every
  test fixture in this suite is a **hand-written inline dict**, never a
  captured real API response or real HTML page. This means the test suite
  validates against the *assumed* IXL response shape (as documented in
  `NOTES.md`), not the actual one — a real production bug caused by an
  undocumented shape difference cannot currently be reproduced from this
  repo's fixtures alone; it would require a live account.

## Structural notes for agents navigating this repo

- **`.worktrees/exit-codes-and-command-outcomes/` is a broken linked git
  worktree on this host.** Its `.git` file points to
  `gitdir: /var/home/user/Documents/vibe-code/openclaw-programs/school/ixl-scrape/.git/worktrees/exit-codes-and-command-outcomes`,
  a path that does not exist here. Running any `git` command *inside* that
  directory (`git status`, `git log`, `git diff`) will fail with
  `fatal: not a git repository`. This is a pre-existing hygiene issue (repo
  was likely copied/relocated without `git worktree repair`), not something
  introduced by this audit — do not attempt to fix it from inside an agent
  session; it needs a human to run `git worktree repair` or
  `git worktree remove` from the main checkout. Treat the directory as
  read-only/inspect-only.
- There are also four `prunable` worktrees under `.claude/worktrees/agent-*`
  (`agent-a1543fad`, `agent-a3cc8077`, `agent-a4862e6b`, `agent-ae701f9a`),
  all pinned at the same commit — these look like leftover scratch worktrees
  from prior automated-agent sessions. Same guidance: read-only, flag for a
  human to prune, don't fix inline.
- `ixl_cli/scrapers/skills.py::scrape_skills()` is the most structurally
  complex scraper (grade-discovery scan of default±4 grades, times 3
  subjects) and has no schema validation on the deeply-nested JSON it parses
  — see `.agent_native/agent_roadmap.md` item 2 before assuming an empty
  skills list means "no data" rather than "couldn't parse the response."

## Privacy

This tool scrapes children's IXL learning data (diagnostics, skills,
SmartScores, usage). When working in this repo:
- Never write real student names, scores, emails, or credentials into any
  file under `.agent_native/`, `CLAUDE.md`, commit messages, or PR
  descriptions.
- `.env.example` and `cron/accounts.env.example` in this repo contain
  placeholders only (`jdoe@myschool`, `your-password`) — verified during this
  audit. If a real credential or token is ever found committed, flag it by
  file path and line only (never quote the value) and treat it as a
  rotate-immediately security incident per the global security rules.
