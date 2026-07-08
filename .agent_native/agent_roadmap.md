# Agent-Native Roadmap — ixl-scrape

Purpose: make it possible for an AI coding agent to pick up a bug report or
feature request against `ixl-scrape` and autonomously reproduce, implement,
test, and verify it — with minimal human judgment calls. Items are ordered by
**Human-Attention-Saved per Unit of Effort** (highest leverage first). No
student data, credentials, or secrets are referenced below — only file paths,
selectors, and structural notes.

This audit is static/code-review only; nothing here required or performed a
live scrape.

---

## 1. Capture a real (redacted) IXL login-page DOM fixture + selector regression test

**Why this is #1:** `ixl_cli/session.py::_do_login()` hard-codes five DOM
selectors against IXL's live login page (`#siusername`, `#sipassword`,
`#custom-signin-button`, the `**/dashboard**` redirect wait, and the
`.error-message, .signin-error, #signin-error` error-detection selectors).
`NOTES.md` documents these as prose ("Form ID: `#customSigninForm`", "Submit
button: `#custom-signin-button`", etc.) but there is **no machine-checkable
artifact** anywhere in the repo (confirmed: no `tests/fixtures/`, no `.html`
files exist outside `.worktrees/`). `mock_session` in `tests/conftest.py`
bypasses `IXLSession.__init__` entirely and is never wired to Playwright, so
none of the 10 test files exercise `_do_login()`'s selector logic against
anything resembling real markup — `test_session.py::TestLoginFailure` mocks
`page`/`context`/`browser` as bare `MagicMock()`s, which validates the
*exception-handling* path (Bug #6 regression) but asserts nothing about
selector correctness. If IXL renames `#siusername` tomorrow, nothing in this
repo will fail until a real cron run does.

**Action:**
- Add `tests/fixtures/ixl_signin_page.html` — a hand-built (not scraped-and-committed-verbatim; synthesize from the selectors in `NOTES.md`) minimal HTML page containing the exact ids/classes `_do_login()` queries: `#siusername`, `#sipassword`, `#custom-signin-button`, and a `.signin-error` element.
- Add `tests/test_login_selectors.py` that loads the fixture with Playwright (or `BeautifulSoup` if a lighter static-HTML pass is acceptable — see item 2 for schema-validation precedent) and asserts each selector `_do_login()` depends on resolves against the fixture.
- Parametrize so removing/renaming any one selector in the fixture causes a clear failure naming *which* selector broke.

**Acceptance criteria:** the new test fails when a selector is renamed in the fixture (e.g. rename `#siusername` → `#username`) and passes against the current `ixl_cli/session.py`. This converts "IXL changed their login page" from a production incident into a local regression-test failure.

---

## 2. Surface scraper schema-drift as a `warnings[]` entry, not a silent stderr log

**Why:** `ixl_cli/scrapers/skills.py::scrape_skills()` (the most complex
scraper — up to 3 subjects × 9 grades of API calls) parses deeply nested IXL
JSON (`gradesModeData.table[].categories[].skills[]`) using only
`isinstance()` guards and `.get()` fallbacks — **no schema validation**
(confirmed: no pydantic/dataclass/jsonschema anywhere in `ixl_cli/`). If IXL
renames `gradesModeData` or restructures `table`/`categories`/`skills`, every
call silently returns `[]` and the only signal is a single
`_log("Warning: No skill data found.", ...)` call — which prints to stderr
only when `verbose=True`, and is **not** added to the `warnings[]` array in
the JSON envelope described in `README.md`'s "JSON Output Contract" section.
An agent (or the OpenClaw cron consumer) reading `--json` output would see a
clean `"status": "ok"` with an empty skills list and have no structured
signal that something broke vs. the student simply having no data yet.

**Action:**
- In `ixl_cli/cli.py` wherever `scrape_skills`/`scrape_diagnostics`/`scrape_trouble_spots`/`scrape_usage` results feed into `make_result(...)`, add an `add_warning(..., code="skills.empty_or_schema_drift", ...)` when a scraper returns empty *and* the API call itself succeeded (200) — distinguishing "genuinely no data" from "got a 200 but couldn't parse it" requires scrapers to return a sentinel or a `(data, parse_ok)` tuple instead of silently coercing to `[]`.
- Add a test in `tests/test_scrapers.py` that feeds `scrape_skills` a 200 response with an unrecognized top-level shape (e.g. `{"gradesModeDataV2": {...}}`) and asserts the caller-visible result signals degraded parsing, not silent success.

**Acceptance criteria:** a schema-shape test in `tests/test_scrapers.py` failing today (no such distinction exists) and passing once the warning path is added; `ixl summary --json` against a malformed-shape mock shows a non-empty `warnings[]` array.

---

## 3. Fix and test `cmd_compare`'s un-restored global env-var mutation

**STATUS: DONE (2026-07-07 agent pass).** `cmd_compare()` in `ixl_cli/cli.py`
now snapshots `IXL_EMAIL`/`IXL_PASSWORD` before the account loop and restores
them (or deletes them if they were unset) in a `finally` block, so the loop
runs regardless of success/failure and env state never leaks past the call.
Added `tests/test_compare.py::test_cmd_compare_restores_env_after_loop`,
`test_cmd_compare_restores_env_when_previously_unset`, and
`test_cmd_compare_continues_after_one_account_fails`; existing
`test_compare.py`/`test_cli.py` tests pass unmodified.

**Why:** `ixl_cli/cli.py::cmd_compare()` (lines ~641-705) iterates
`~/.ixl/accounts.env` accounts and does
`os.environ["IXL_EMAIL"] = acct["email"]` / `os.environ["IXL_PASSWORD"] = ...`
in-place, in a loop, inside a single Python process — and **never restores**
the original env vars after the loop finishes (confirmed by reading the full
function body through its `return result`). This pattern is not documented
anywhere as a caveat (not in `README.md`, not in `NOTES.md`, not in the
parent `school/CLAUDE.md`). It is safe for the CLI entry point itself
(process exits), but is a live footgun for:
  - any future code that imports and calls `cmd_compare()` programmatically in a longer-lived process (tests already do this pattern for `cmd_assigned` in `test_scrapers.py::TestCmdAssigned`, so it's a plausible future test target too),
  - the failure-recovery path: a per-account exception is caught and logged as a `compare.account_failed` warning, but the env vars from the *failing* account remain set in `os.environ` until overwritten by the next loop iteration (or leaked to the caller if it's the last account and it fails).
- `tests/test_compare.py` only tests `load_accounts()` and `build_comparison()` in isolation — the actual multi-account iteration loop in `cmd_compare()` (the env-var-overwrite mechanism itself) has **zero test coverage**.

**Action:**
- Wrap the loop body in `cmd_compare()` with a `try/finally` (or use `unittest.mock.patch.dict(os.environ, ...)`-style scoping refactored into production code) that restores the pre-loop `IXL_EMAIL`/`IXL_PASSWORD` (or deletes them if unset) after the loop, success or failure.
- Add `tests/test_compare.py::test_cmd_compare_restores_env_after_loop` and `test_cmd_compare_continues_after_one_account_fails` that patch `IXLSession`/scrapers and assert (a) env vars are restored to their pre-call values, and (b) a failure on account N doesn't corrupt data collected for accounts N+1..end.

**Acceptance criteria:** new tests fail against current `cli.py` (env vars leak) and pass after the fix; existing `test_compare.py` tests still pass unmodified.

---

## 4. Resolve the stale/orphaned git worktrees before an agent trips over them

**Why:** `git worktree list` from the main repo shows **five** linked
worktrees, four of which (`agent-a1543fad`, `agent-a3cc8077`, `agent-a4862e6b`,
`agent-ae701f9a`) are marked `prunable` and live under
`.claude/worktrees/agent-*`, plus `.worktrees/exit-codes-and-command-outcomes`
on branch `feat/exit-codes-and-command-outcomes`. That fifth worktree's
`.git` file points to
`gitdir: /var/home/user/Documents/vibe-code/openclaw-programs/school/ixl-scrape/.git/worktrees/exit-codes-and-command-outcomes`
— a path that does not exist on this host (this repo actually lives under
`/home/user/Documents/vibe-code/school/ixl-scrape`). Any `git` command run
*inside* that worktree directory (`git status`, `git log`, `git diff`)
currently fails with `fatal: not a git repository`. An agent that `cd`s into
`.worktrees/exit-codes-and-command-outcomes/` expecting a normal git checkout
(the directory looks identical to the main repo — same `ixl_cli/`, `tests/`,
`Makefile`, etc.) will hit a confusing, unexplained git failure with no clue
that the worktree's back-reference is broken (likely from the whole
`school/` tree being copied/relocated between machines/paths without
`git worktree repair`).

**Action (documentation-first, since this task is read-only w.r.t. `.worktrees/`):**
- Document this exact failure mode and its cause in the new `CLAUDE.md` (done as part of this audit — see file) so an agent that hits `fatal: not a git repository` inside `.worktrees/exit-codes-and-command-outcomes/` immediately knows why, instead of spending a debugging pass on it.
- Recommend the repo owner (human, not an agent) run `git worktree repair` from the main checkout, or `git worktree remove --force .worktrees/exit-codes-and-command-outcomes` if the in-flight branch work is abandoned/superseded, and separately decide whether the four `prunable` `.claude/worktrees/agent-*` checkouts (all four are stuck at the same commit `f041119`, name pattern suggests automated-agent-session scratch worktrees) should be pruned with `git worktree prune`.

**Acceptance criteria:** the CLAUDE.md addition alone satisfies the "agent doesn't get stuck" goal (this item's real fix — `git worktree repair`/`remove` — is a human decision since it touches branch state the audit was told not to disturb).

---

## 5. Build a captured-real-response fixture corpus for scraper reproduction

**STATUS: PARTIAL — DONE for skills.py (2026-07-07 agent pass).** Added
`tests/fixtures/api_responses/score_chart_run.json`, a SYNTHETIC (explicitly
labeled as such in an `_fixture_note` field, not a live capture — no live
account was used or available) fixture matching the
`gradesModeData.table[].categories[].skills[]` shape documented in
`NOTES.md`. `tests/test_skills.py::TestScrapeSkillsFixtureShape` loads it and
asserts `scrape_skills()`'s full field-mapping path (permacode, skillName,
score, secondsSpent→time_spent_min, questionsAnswered, skill_code
composition, category, suggested) against it, replacing what had been a gap
(no test previously exercised that mapping against a table/categories/skills
shaped payload at all). The other four endpoints listed below
(`student_summary_practice.json`, `trouble_spots_run.json`,
`student_usage_run.json`, `diagnostic_growth.json`) are **not yet done** —
still inline hand-typed dicts, and a real fixture capture from a live/test
account (not just synthesized from `NOTES.md`) remains the higher-value
follow-up this item originally called for.

**Why:** Every JSON fixture across `tests/test_scrapers.py`,
`tests/test_skills.py`, `tests/test_session.py`, etc. is **hand-written**
inline in the test file (e.g. the `diagnosticGrowthOverTime` / `table` /
`gradesModeData` shapes are typed out by a human/agent from memory of the API
per `NOTES.md`'s endpoint table, not captured from a live response). This
means: (a) a real bug where IXL's actual response has a slightly different
shape than what's hand-typed in the tests cannot be reproduced from the
existing suite — the tests would keep passing against the *assumed* shape
while production breaks against the *real* shape; (b) there's no ground
truth to diff against when investigating "the scraper returns wrong data"
reports.

**Action:**
- Establish `tests/fixtures/api_responses/` with one JSON file per endpoint (`score_chart_run.json`, `student_summary_practice.json`, `trouble_spots_run.json`, `student_usage_run.json`, `diagnostic_growth.json`) — captured once from a real (test/throwaway) account with all student-identifying fields replaced by placeholders (`"Test Student"`, fake ids), then load these fixtures in `make_response(...)` calls instead of the current inline hand-typed dicts.
- This does not require a live account for *this* audit or for future bug reproduction — once captured, the fixture is reusable and the capture step only needs to happen once (or be re-run when a real production discrepancy is found, at which point the newly-captured fixture becomes the regression test for that specific bug).

**Acceptance criteria:** at least one scraper (`skills.py`, since it's the most structurally complex) has its test suite switched from inline dicts to a loaded fixture file, and a comment in the fixture file notes the capture date and that student-identifying fields were redacted.

---

## Verified during this audit: `TestLoginFailure` doesn't actually mock Playwright

**STATUS: FIXED (2026-07-07 agent pass).** `ixl_cli/session.py` now imports
`sync_playwright` at module scope (`try: from playwright.sync_api import
sync_playwright / except ImportError: sync_playwright = None`), guarded so
Playwright stays optional, instead of importing it lazily inside
`_do_login()`. `_do_login()` now checks `if sync_playwright is None:` instead
of catching `ImportError` locally. This makes
`patch("ixl_cli.session.sync_playwright", ...)` in
`tests/test_session.py::TestLoginFailure` actually intercept the call (it
previously patched a name that didn't exist at module scope and had zero
effect — `create=True` silently conjured a throwaway attribute). Added
`mock_playwright_fn.assert_called_once()` /
`mock_pw_instance.chromium.launch.assert_called_once_with(headless=True)` /
`mock_page.goto.assert_called()` assertions to the test so a regression back
to a function-local import (which would make the mock chain never get
called, and a real browser get launched instead) fails loudly instead of
silently attempting a real network-backed browser launch. Confirmed: the
test now runs in ~0.04s (fully mocked, no browser process) versus ~15.8s
before the fix (real Chromium launch + real network attempt to IXL's live
site — a hazard this fix also eliminates for local test runs).

Running `python3 -m pytest -q --tb=short` on this host (playwright package
installed, but no Chromium browser binary downloaded) produced:
`1 failed, 123 passed` — the one failure is
`tests/test_session.py::TestLoginFailure::test_login_failure_before_cookies_gives_runtime_error`,
with a real `playwright._impl._errors.Error: BrowserType.launch: Executable
doesn't exist at .../chrome-headless-shell` traceback, i.e. it tried to
launch a **real browser**.

Root cause: this test does
`patch("ixl_cli.session.sync_playwright", mock_playwright_fn, create=True)`,
but `ixl_cli/session.py::_do_login()` does a **lazy, function-local** import
(`from playwright.sync_api import sync_playwright`, inside the function body,
specifically to keep Playwright optional per the module docstring). A
function-local import resolves the real `playwright.sync_api.sync_playwright`
at call time — patching the `ixl_cli.session` module attribute (which
`create=True` conjures into existence for the patch, since it doesn't
normally exist as a module-level name) has no effect on what the function
actually calls. So this regression test for "Bug #6: UnboundLocalError when
login fails before cookie_dict is assigned" is **not hermetic** — it only
exercises the mocked path (and thus only proves the bug is fixed) on a
machine that happens to not have Chromium installed in a way that raises
*before* reaching the mocked logic, or conversely will attempt a real browser
launch and fail/skip unpredictably depending on local Playwright install
state. On a machine with Chromium installed, this test would silently pass
by actually driving a real (offline, will-fail-differently) browser instead
of testing the intended code path at all.

**Action:** patch at the true call site. Either (a) patch
`playwright.sync_api.sync_playwright` directly (the actual module-level
name), or (b) refactor `_do_login()` to import `sync_playwright` at module
scope guarded by a `try/except ImportError` flag instead of a function-local
import, so `patch("ixl_cli.session.sync_playwright", ...)` works as the test
author intended. Add an assertion in the test (e.g. a call-count check on
the mock) that fails loudly if the mock was never invoked, so this class of
"looks mocked, isn't" bug can't silently regress again.

**Acceptance criteria:** `pytest tests/test_session.py::TestLoginFailure -v`
passes deterministically on a machine with *no* Playwright browsers
installed, and the test fails (not errors with a browser-launch traceback)
if the `_do_login` code under test is reverted to reintroduce the original
`UnboundLocalError` bug.

---

## Lower-priority / longer-horizon items (not in the immediate top 5)

- **`goals.py`/`history.py`/`notify.py`/`export.py` were not deep-audited in this pass** — the task scope centered on session/login/multi-account/scraper reproduction; a follow-up pass should apply the same "real fixture vs. hand-written mock" lens to `history.py`'s snapshot format.
- **`ixl_cli/scrapers/skills.py` is doing a lot in one function** (`scrape_skills`) — grade-discovery, subject iteration, and per-skill field mapping are all inlined; extracting `_map_skill_fields(sk, cat_name, cat_code)` as a named, independently-testable function would shrink the blast radius of a future API-shape change.
- **`cron/ixl-cron.sh` is actually well-isolated** (each account's credentials are scoped to a single subshell-prefixed `ixl` invocation — a fresh process per account) and is *not* subject to the env-leak problem in item 3; this is worth noting so a future agent doesn't conflate the two code paths.
- **Version drift**: `pyproject.toml` reports `version = "0.16.5"`, while the parent `school/CLAUDE.md` describes this repo as `v0.2.0`. Not fixed here (parent CLAUDE.md is out of scope), but worth flagging so an agent doesn't assume the parent doc's version number is current.
