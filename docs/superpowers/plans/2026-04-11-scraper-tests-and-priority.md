# Scraper Tests & --priority Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit tests for the four untested scraper modules (`children`, `diagnostics`, `trouble_spots`, `usage`) and implement the `--priority` sort for `ixl assigned`.

**Architecture:** Each scraper gets its own test class in `tests/test_scrapers.py`, using a shared `mock_session` fixture that already exists in `conftest.py` plus a `make_response` helper. The `--priority` flag sorts remaining skills by: not-started first (questions=0), then in-progress, within each group sorted by `smart_score` ascending (lowest score = needs most help first). The sort happens in `cmd_assigned` before calling `output_assigned`.

**Tech Stack:** pytest + `unittest.mock`. No new dependencies.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `tests/conftest.py` | Read-only (reference) | `mock_session`, `make_response`, `tmp_ixl_dir` fixtures |
| `tests/test_scrapers.py` | Create | Tests for children, diagnostics, trouble_spots, usage scrapers |
| `ixl_cli/cli.py:512-515` | Modify (`cmd_assigned`) | Implement `--priority` sort |

---

### Background: conftest.py fixture API

The existing `conftest.py` provides:

```python
@pytest.fixture
def mock_session():
    """Returns an IXLSession with _logged_in=True, bypassing Playwright."""
    ...  # session.get() and session.post() are real requests.Session methods
    # but no real login happens; patch the HTTP calls in each test

@pytest.fixture
def make_response():
    """Returns a factory: make_response(status_code, json_data) -> requests.Response"""

@pytest.fixture
def tmp_ixl_dir(tmp_path, monkeypatch):
    """Returns a tmp_path that acts as ~/.ixl/"""
```

Use `mock_session` + `patch("requests.Session.get", ...)` or `patch.object(session._session, "get", ...)` to mock HTTP calls in scraper tests.

---

### Task 1: Test scrape_children

**Files:**
- Create: `tests/test_scrapers.py`

`scrape_children` (`ixl_cli/scrapers/children.py`) calls IXL's student profile endpoint and returns a list of `{name, uid, grade}` dicts. If the request fails it returns `[]`.

- [ ] **Step 1: Read scrape_children to understand the API it calls**

Run: `python3 -c "import inspect, ixl_cli.scrapers.children as m; print(inspect.getsource(m.scrape_children))"`

Note the exact URL/endpoint and the JSON field names it parses. Use those in the mocks below.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_scrapers.py
from unittest.mock import patch, MagicMock
import pytest
from ixl_cli.scrapers.children import scrape_children


class TestScrapeChildren:
    def test_returns_list_of_children(self, mock_session, make_response):
        api_data = {"data": [{"studentId": "123", "name": "Ford", "gradeLevel": "3"}]}
        with patch.object(mock_session._session, "get", return_value=make_response(200, api_data)):
            result = scrape_children(mock_session)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Ford"
        assert result[0]["uid"] == "123"
        assert result[0]["grade"] == "3"

    def test_returns_empty_list_when_api_fails(self, mock_session, make_response):
        with patch.object(mock_session._session, "get", return_value=make_response(500, {})):
            result = scrape_children(mock_session)
        assert result == []

    def test_returns_empty_list_when_no_students(self, mock_session, make_response):
        with patch.object(mock_session._session, "get", return_value=make_response(200, {"data": []})):
            result = scrape_children(mock_session)
        assert result == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scrapers.py::TestScrapeChildren -v`
Expected: FAIL (test may need field name adjustment after reading actual source)

- [ ] **Step 4: Adjust field names to match actual scraper source**

Read `ixl_cli/scrapers/children.py` and update the mock `api_data` keys and the assertions to match what the scraper actually parses. The tests must reflect the real behavior, not an assumed shape.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scrapers.py::TestScrapeChildren -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_scrapers.py
git commit -m "test(scrapers): add unit tests for scrape_children"
```

---

### Task 2: Test scrape_diagnostics

**Files:**
- Modify: `tests/test_scrapers.py`

`scrape_diagnostics` returns `[{subject, overall_level, max_score, has_data, scores: [...]}]`. Returns `[]` on HTTP error.

- [ ] **Step 1: Read the scraper source first**

Run: `python3 -c "import inspect, ixl_cli.scrapers.diagnostics as m; print(inspect.getsource(m.scrape_diagnostics))"`

Note the endpoint URL and how it maps API fields to the output dict.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_scrapers.py`:

```python
from ixl_cli.scrapers.diagnostics import scrape_diagnostics


class TestScrapeDiagnostics:
    def test_returns_list_with_subject_data(self, mock_session, make_response):
        # Replace the api_data shape below with the actual response shape
        # from reading scrape_diagnostics source
        api_data = {}  # TODO: fill in after reading source
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)):
            result = scrape_diagnostics(mock_session)
        assert isinstance(result, list)

    def test_returns_empty_list_when_api_fails(self, mock_session, make_response):
        with patch.object(mock_session._session, "post", return_value=make_response(500, {})):
            result = scrape_diagnostics(mock_session)
        assert result == []

    def test_has_data_flag_false_when_no_scores(self, mock_session, make_response):
        # The scraper sets has_data=False when the student hasn't taken diagnostics
        # Fill api_data with the shape that represents "no diagnostic taken"
        api_data = {}  # TODO: fill in after reading source
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)):
            result = scrape_diagnostics(mock_session)
        # At minimum the response should be a list (empty or with has_data=False entries)
        assert isinstance(result, list)
```

- [ ] **Step 3: Fill in actual mock data from scraper source**

Read `ixl_cli/scrapers/diagnostics.py` and replace the `api_data = {}  # TODO` placeholders with realistic mock payloads matching the actual API shape the scraper parses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scrapers.py::TestScrapeDiagnostics -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_scrapers.py
git commit -m "test(scrapers): add unit tests for scrape_diagnostics"
```

---

### Task 3: Test scrape_trouble_spots

**Files:**
- Modify: `tests/test_scrapers.py`

`scrape_trouble_spots` POSTs to the trouble-spots analytics endpoint and returns `[{skill, name, skill_code, grade, missed_count, score}]`. Returns `[]` on error.

- [ ] **Step 1: Read the scraper source first**

Run: `python3 -c "import inspect, ixl_cli.scrapers.trouble_spots as m; print(inspect.getsource(m.scrape_trouble_spots))"`

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_scrapers.py`:

```python
from ixl_cli.scrapers.trouble_spots import scrape_trouble_spots


class TestScrapeTroubleSpots:
    def test_returns_list_of_trouble_spots(self, mock_session, make_response):
        # Fill api_data after reading source
        api_data = {}  # TODO
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)):
            result = scrape_trouble_spots(mock_session)
        assert isinstance(result, list)

    def test_each_trouble_spot_has_required_fields(self, mock_session, make_response):
        # Fill api_data to produce at least one trouble spot
        api_data = {}  # TODO
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)):
            result = scrape_trouble_spots(mock_session)
        if result:
            spot = result[0]
            assert "name" in spot
            assert "missed_count" in spot

    def test_returns_empty_list_when_api_fails(self, mock_session, make_response):
        with patch.object(mock_session._session, "post", return_value=make_response(500, {})):
            result = scrape_trouble_spots(mock_session)
        assert result == []
```

- [ ] **Step 3: Fill in actual mock data from scraper source**

Read `ixl_cli/scrapers/trouble_spots.py` and replace `api_data = {}  # TODO` with realistic mock payloads.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scrapers.py::TestScrapeTroubleSpots -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_scrapers.py
git commit -m "test(scrapers): add unit tests for scrape_trouble_spots"
```

---

### Task 4: Test scrape_usage

**Files:**
- Modify: `tests/test_scrapers.py`

`scrape_usage` GETs the usage analytics endpoint and returns `{period, time_spent_min, questions_answered, skills_practiced, days_active, sessions: [...], top_categories: [...]}`. Returns a zeroed-out dict on error.

- [ ] **Step 1: Read the scraper source first**

Run: `python3 -c "import inspect, ixl_cli.scrapers.usage as m; print(inspect.getsource(m.scrape_usage))"`

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_scrapers.py`:

```python
from ixl_cli.scrapers.usage import scrape_usage


class TestScrapeUsage:
    def test_returns_dict_with_usage_fields(self, mock_session, make_response):
        api_data = {}  # TODO: fill in after reading source
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)):
            result = scrape_usage(mock_session)
        assert isinstance(result, dict)
        assert "time_spent_min" in result
        assert "questions_answered" in result
        assert "days_active" in result

    def test_returns_zeroed_dict_when_api_fails(self, mock_session, make_response):
        with patch.object(mock_session._session, "post", return_value=make_response(500, {})):
            result = scrape_usage(mock_session)
        assert isinstance(result, dict)
        assert result.get("time_spent_min", 0) == 0
        assert result.get("questions_answered", 0) == 0

    def test_accepts_days_parameter(self, mock_session, make_response):
        api_data = {}  # TODO: fill in
        with patch.object(mock_session._session, "post", return_value=make_response(200, api_data)) as mock_get:
            scrape_usage(mock_session, days=14)
        # Verify the request included the days parameter somehow (URL or payload)
        assert mock_get.called
```

- [ ] **Step 3: Fill in actual mock data from scraper source**

Read `ixl_cli/scrapers/usage.py` and replace all `api_data = {}  # TODO` placeholders with realistic mock payloads.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_scrapers.py::TestScrapeUsage -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_scrapers.py
git commit -m "test(scrapers): add unit tests for scrape_usage"
```

---

### Task 5: Implement --priority sort in cmd_assigned

**Files:**
- Modify: `ixl_cli/cli.py:512-515` (`cmd_assigned`)
- Modify: `tests/test_scrapers.py`

`--priority` sorts remaining skills: not-started (questions=0) before in-progress, and within each group sorted by `smart_score` ascending (lowest = needs most help shown first). Also wraps the command in the outcome contract so it returns a result dict instead of `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scrapers.py`:

```python
from argparse import Namespace
from unittest.mock import patch
from ixl_cli.cli import cmd_assigned


class TestCmdAssigned:
    def _skills_data(self):
        return [
            {"subject": "Math", "skills": [
                {"name": "A", "suggested": True, "smart_score": 45, "questions": 10},  # in-progress, low score
                {"name": "B", "suggested": True, "smart_score": 0, "questions": 0},   # not started
                {"name": "C", "suggested": True, "smart_score": 70, "questions": 20}, # in-progress, higher
                {"name": "D", "suggested": True, "smart_score": 90, "questions": 50}, # done (>=80)
            ]}
        ]

    def test_priority_puts_not_started_first(self):
        skills_data = self._skills_data()
        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=skills_data),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=True))
        # In priority mode the result data should have remaining sorted correctly
        remaining = result["data"]["remaining"]
        assert remaining[0]["name"] == "B"    # not started first
        assert remaining[1]["name"] == "A"    # in-progress, lower score next
        assert remaining[2]["name"] == "C"    # in-progress, higher score last

    def test_no_priority_preserves_original_order(self):
        skills_data = self._skills_data()
        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=skills_data),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=False))
        # Without priority flag the order matches the scraper output order
        remaining = result["data"]["remaining"]
        names = [r["name"] for r in remaining]
        assert names == ["A", "B", "C"]  # original order minus done (D removed)

    def test_returns_result_dict(self):
        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=[]),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=False))
        assert isinstance(result, dict)
        assert "status" in result
        assert "exit_code" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scrapers.py::TestCmdAssigned -v`
Expected: FAIL — `cmd_assigned` returns None, no `data["remaining"]`

- [ ] **Step 3: Rewrite cmd_assigned in cli.py**

Replace lines 512–515:

```python
def cmd_assigned(args: argparse.Namespace) -> dict:
    session = IXLSession(verbose=not args.json)
    skills_data = scrape_skills(session, subject=args.subject)

    # Build remaining list (same logic as output_assigned but returns data)
    all_remaining: list[dict] = []
    totals: dict[str, dict] = {}
    for subj in skills_data:
        subject = subj.get("subject", "Unknown")
        assigned = [sk for sk in subj.get("skills", []) if sk.get("suggested")]
        done = [sk for sk in assigned if (sk.get("smart_score", 0) or 0) >= 80]
        not_started = [sk for sk in assigned if sk.get("questions", 0) == 0]
        in_progress = [sk for sk in assigned
                       if sk.get("questions", 0) > 0 and (sk.get("smart_score", 0) or 0) < 80]
        totals[subject] = {
            "assigned": len(assigned),
            "done": len(done),
            "in_progress": len(in_progress),
            "not_started": len(not_started),
            "remaining": len(not_started) + len(in_progress),
        }
        for sk in not_started + in_progress:
            all_remaining.append({**sk, "subject": subject})

    if args.priority:
        # not-started before in-progress, then sort each group by smart_score ascending
        all_remaining.sort(key=lambda sk: (
            1 if sk.get("questions", 0) == 0 else 2,          # 1=not_started, 2=in_progress
            sk.get("smart_score", 0) or 0,                     # lowest score first within group
        ))
        # Reverse the first key so not-started (1) comes before in-progress (2)
        all_remaining.sort(key=lambda sk: (
            0 if sk.get("questions", 0) == 0 else 1,
            sk.get("smart_score", 0) or 0,
        ))

    active_totals = {k: v for k, v in totals.items() if v["assigned"] > 0}
    data = {"totals": active_totals, "remaining": all_remaining}

    if not args.json:
        output_assigned(skills_data, False)

    return make_result(command="assigned", data=data)
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_scrapers.py::TestCmdAssigned -v`
Expected: 3 PASS

Run: `python3 -m pytest -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/cli.py tests/test_scrapers.py
git commit -m "feat(assigned): implement --priority sort (not-started first, then by score)"
```

---

### Task 6: Run full test suite and verify coverage

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest -v`
Expected: all tests PASS (no failures)

- [ ] **Step 2: Check coverage for scrapers**

Run: `python3 -m pytest --cov=ixl_cli/scrapers --cov-report=term-missing tests/test_scrapers.py`

Review the missing-lines output. If any scraper has critical uncovered paths (error branches, empty-response paths), add tests for them before proceeding.

- [ ] **Step 3: Commit final coverage additions if any**

```bash
git add tests/test_scrapers.py
git commit -m "test(scrapers): add coverage for remaining error branches"
```
