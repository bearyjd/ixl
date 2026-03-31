# Goal Tracking & Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add weekly goal tracking so parents can set targets (time, questions, mastery, active days, trouble spots) and see progress vs goals.

**Architecture:** New `ixl_cli/goals.py` module handles config I/O, smart defaults generation, and goal evaluation. CLI integration via new `goals` subcommand and embedded goals section in `summary`. All goal logic is pure functions operating on scraper output dicts — no direct API calls.

**Tech Stack:** Python stdlib only (json, os, math, datetime). No new dependencies.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `ixl_cli/goals.py` | Create | load/save config, generate defaults, evaluate progress |
| `ixl_cli/session.py` | Modify (1 line) | Add `GOALS_PATH` constant |
| `ixl_cli/cli.py` | Modify | Add `goals` subcommand, embed goals in summary output |
| `tests/test_goals.py` | Create | Unit tests for all goals logic |

---

### Task 1: Add GOALS_PATH constant and create goals.py with load/save

**Files:**
- Modify: `ixl_cli/session.py:28` (add constant after SESSION_PATH)
- Create: `ixl_cli/goals.py`
- Create: `tests/test_goals.py`

- [ ] **Step 1: Write failing tests for load_goals and save_goals**

```python
# tests/test_goals.py
"""Tests for ixl_cli.goals."""

import json
import os
from unittest.mock import patch

import pytest


class TestLoadGoals:
    """Config loading from goals.json."""

    def test_missing_goals_returns_none(self, tmp_ixl_dir):
        """load_goals returns None when file doesn't exist."""
        from ixl_cli.goals import load_goals

        with patch("ixl_cli.goals.GOALS_PATH", tmp_ixl_dir / "goals.json"):
            assert load_goals() is None

    def test_malformed_goals_returns_none(self, tmp_ixl_dir):
        """load_goals returns None on invalid JSON."""
        from ixl_cli.goals import load_goals

        goals_path = tmp_ixl_dir / "goals.json"
        goals_path.write_text("{bad json")

        with patch("ixl_cli.goals.GOALS_PATH", goals_path):
            assert load_goals() is None

    def test_valid_goals_loaded(self, tmp_ixl_dir):
        """load_goals returns parsed dict on valid JSON."""
        from ixl_cli.goals import load_goals

        goals_path = tmp_ixl_dir / "goals.json"
        goals_data = {"weekly": {"time_min": 150, "questions": 300}}
        goals_path.write_text(json.dumps(goals_data))

        with patch("ixl_cli.goals.GOALS_PATH", goals_path):
            result = load_goals()

        assert result == goals_data


class TestSaveGoals:
    """Config writing to goals.json."""

    def test_goals_json_roundtrip(self, tmp_ixl_dir):
        """Goals survive write-then-read."""
        from ixl_cli.goals import load_goals, save_goals

        goals_path = tmp_ixl_dir / "goals.json"
        goals_data = {
            "weekly": {
                "time_min": 150,
                "questions": 300,
                "skills_mastered": 3,
                "days_active": 5,
                "trouble_spots_reduced": 2,
            }
        }

        with patch("ixl_cli.goals.GOALS_PATH", goals_path), \
             patch("ixl_cli.goals.IXL_DIR", tmp_ixl_dir):
            save_goals(goals_data)
            result = load_goals()

        assert result == goals_data

    def test_goals_file_permissions(self, tmp_ixl_dir):
        """Goals file created with 0o600 permissions."""
        from ixl_cli.goals import save_goals

        goals_path = tmp_ixl_dir / "goals.json"

        with patch("ixl_cli.goals.GOALS_PATH", goals_path), \
             patch("ixl_cli.goals.IXL_DIR", tmp_ixl_dir):
            save_goals({"weekly": {"time_min": 60}})

        mode = oct(goals_path.stat().st_mode & 0o777)
        assert mode == "0o600"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals.py -v`
Expected: ImportError — `ixl_cli.goals` does not exist yet

- [ ] **Step 3: Implement load_goals and save_goals**

Add to `ixl_cli/session.py` after line 28 (`SESSION_PATH = ...`):
```python
GOALS_PATH = IXL_DIR / "goals.json"
```

Create `ixl_cli/goals.py`:
```python
"""
IXL goal tracking — weekly targets and progress evaluation.

Goals are stored in ~/.ixl/goals.json and evaluated against
current week's scraper data.
"""

import json
import math
import os
from datetime import date, timedelta

from ixl_cli.session import GOALS_PATH, IXL_DIR, _ensure_dir, _log


def load_goals() -> dict | None:
    """Load goals from ~/.ixl/goals.json. Returns None if missing or malformed."""
    if not GOALS_PATH.exists():
        return None
    try:
        with open(GOALS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_goals(goals: dict) -> None:
    """Atomic write goals to ~/.ixl/goals.json with 0o600 permissions."""
    _ensure_dir()
    tmp_path = GOALS_PATH.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(goals, f, indent=2)
        f.write("\n")
    os.replace(str(tmp_path), str(GOALS_PATH))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/session.py ixl_cli/goals.py tests/test_goals.py
git commit -m "feat(goals): add goals config load/save with atomic writes"
```

---

### Task 2: Implement generate_defaults

**Files:**
- Modify: `ixl_cli/goals.py`
- Modify: `tests/test_goals.py`

- [ ] **Step 1: Write failing tests for generate_defaults**

Append to `tests/test_goals.py`:
```python
from ixl_cli.goals import generate_defaults


class TestGenerateDefaults:
    """Smart defaults from recent usage data."""

    def test_generate_defaults_from_usage(self):
        """Defaults computed from 14-day usage data."""
        usage = {
            "period": "last_14_days",
            "time_spent_min": 200,
            "questions_answered": 500,
            "days_active": 8,
        }
        skills_data = [
            {"subject": "Math", "skills": [
                {"smart_score": 95, "name": "A"},
                {"smart_score": 92, "name": "B"},
                {"smart_score": 85, "name": "C"},
                {"smart_score": 50, "name": "D"},
            ]},
            {"subject": "ELA", "skills": [
                {"smart_score": 100, "name": "E"},
            ]},
        ]

        result = generate_defaults(usage, skills_data)
        weekly = result["weekly"]

        # 200 min / 2 weeks = 100/week, round up to 110
        assert weekly["time_min"] == 110
        # 500 / 2 = 250/week, round up to 300
        assert weekly["questions"] == 300
        # 3 mastered (95, 92, 100) / 2 weeks = 1.5, round up = 2
        assert weekly["skills_mastered"] == 2
        # 8 days / 2 = 4/week
        assert weekly["days_active"] == 4
        # always 1
        assert weekly["trouble_spots_reduced"] == 1

    def test_generate_defaults_floors(self):
        """Minimums enforced when usage is very low."""
        usage = {
            "period": "last_14_days",
            "time_spent_min": 10,
            "questions_answered": 5,
            "days_active": 1,
        }
        skills_data = []

        result = generate_defaults(usage, skills_data)
        weekly = result["weekly"]

        assert weekly["time_min"] == 60
        assert weekly["questions"] == 100
        assert weekly["skills_mastered"] == 1
        assert weekly["days_active"] == 3
        assert weekly["trouble_spots_reduced"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals.py::TestGenerateDefaults -v`
Expected: ImportError or AttributeError — `generate_defaults` not defined

- [ ] **Step 3: Implement generate_defaults**

Add to `ixl_cli/goals.py`:
```python
def _round_up_to(value: float, multiple: int) -> int:
    """Round up to the nearest multiple."""
    return int(math.ceil(value / multiple)) * multiple


def generate_defaults(usage: dict, skills_data: list) -> dict:
    """Compute smart weekly goal defaults from 14-day usage data.

    Args:
        usage: Output from scrape_usage(days=14).
        skills_data: Output from scrape_skills().

    Returns dict ready for save_goals().
    """
    total_time = usage.get("time_spent_min", 0)
    total_questions = usage.get("questions_answered", 0)
    total_days_active = usage.get("days_active", 0)

    # Count skills with SmartScore >= 90 across all subjects
    mastered_count = 0
    for subj in skills_data:
        for sk in subj.get("skills", []):
            if (sk.get("smart_score", 0) or 0) >= 90:
                mastered_count += 1

    # Compute weekly averages (14 days = 2 weeks)
    weekly_time = total_time / 2
    weekly_questions = total_questions / 2
    weekly_mastered = mastered_count / 2
    weekly_days = total_days_active / 2

    return {
        "weekly": {
            "time_min": max(60, _round_up_to(weekly_time, 10)),
            "questions": max(100, _round_up_to(weekly_questions, 50)),
            "skills_mastered": max(1, math.ceil(weekly_mastered)),
            "days_active": max(3, math.ceil(weekly_days)),
            "trouble_spots_reduced": 1,
        }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals.py::TestGenerateDefaults -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/goals.py tests/test_goals.py
git commit -m "feat(goals): add smart defaults generation from usage data"
```

---

### Task 3: Implement evaluate_goals

**Files:**
- Modify: `ixl_cli/goals.py`
- Modify: `tests/test_goals.py`

- [ ] **Step 1: Write failing tests for evaluate_goals**

Append to `tests/test_goals.py`:
```python
from ixl_cli.goals import evaluate_goals


class TestEvaluateGoals:
    """Goal status evaluation."""

    def test_evaluate_on_track(self):
        """Metrics within 20% of prorated target are on_track."""
        goals = {"weekly": {
            "time_min": 140,
            "questions": 280,
            "skills_mastered": 7,
            "days_active": 7,
            "trouble_spots_reduced": 1,
        }}
        usage = {"time_spent_min": 60, "questions_answered": 120, "days_active": 3}
        skills_data = [{"subject": "Math", "skills": [
            {"smart_score": 95, "name": "A"},
            {"smart_score": 92, "name": "B"},
            {"smart_score": 91, "name": "C"},
        ]}]
        trouble_spots = [{"skill": "X"}, {"skill": "Y"}]

        # Day 3 of 7: expected pace = target * 3/7
        result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=3)

        assert result["day_of_week"] == 3
        assert result["metrics"]["time_min"]["status"] == "on_track"
        assert result["metrics"]["time_min"]["actual"] == 60
        assert result["metrics"]["time_min"]["target"] == 140

    def test_evaluate_behind(self):
        """Metrics well below prorated target are behind."""
        goals = {"weekly": {
            "time_min": 300,
            "questions": 500,
            "skills_mastered": 5,
            "days_active": 7,
            "trouble_spots_reduced": 1,
        }}
        usage = {"time_spent_min": 10, "questions_answered": 20, "days_active": 1}
        skills_data = []
        trouble_spots = [{"skill": "X"}, {"skill": "Y"}, {"skill": "Z"}]

        result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=5)

        assert result["metrics"]["time_min"]["status"] == "behind"
        assert result["metrics"]["questions"]["status"] == "behind"

    def test_evaluate_ahead(self):
        """Metrics well above prorated target are ahead."""
        goals = {"weekly": {
            "time_min": 100,
            "questions": 200,
            "skills_mastered": 2,
            "days_active": 3,
            "trouble_spots_reduced": 1,
        }}
        usage = {"time_spent_min": 90, "questions_answered": 180, "days_active": 3}
        skills_data = [{"subject": "Math", "skills": [
            {"smart_score": 95, "name": "A"},
            {"smart_score": 92, "name": "B"},
            {"smart_score": 91, "name": "C"},
        ]}]
        trouble_spots = []

        result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=2)

        assert result["metrics"]["time_min"]["status"] == "ahead"
        assert result["metrics"]["questions"]["status"] == "ahead"
        assert result["metrics"]["skills_mastered"]["status"] == "ahead"

    def test_evaluate_pct_calculation(self):
        """Percentage is actual/target * 100, clamped to int."""
        goals = {"weekly": {
            "time_min": 200,
            "questions": 100,
            "skills_mastered": 1,
            "days_active": 5,
            "trouble_spots_reduced": 1,
        }}
        usage = {"time_spent_min": 50, "questions_answered": 75, "days_active": 2}
        skills_data = []
        trouble_spots = []

        result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=4)

        assert result["metrics"]["time_min"]["pct"] == 25
        assert result["metrics"]["questions"]["pct"] == 75
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals.py::TestEvaluateGoals -v`
Expected: ImportError or AttributeError — `evaluate_goals` not defined

- [ ] **Step 3: Implement evaluate_goals**

Add to `ixl_cli/goals.py`:
```python
def _compute_status(actual: float, target: float, day_of_week: int) -> str:
    """Compute goal status: ahead, on_track, behind, or no_data."""
    if target <= 0:
        return "no_data"
    expected_pace = target * (day_of_week / 7)
    if actual >= expected_pace * 1.2:
        return "ahead"
    elif actual >= expected_pace * 0.8:
        return "on_track"
    else:
        return "behind"


def evaluate_goals(
    goals: dict,
    usage: dict,
    skills_data: list,
    trouble_spots: list,
    day_of_week: int | None = None,
) -> dict:
    """Evaluate current progress against weekly goals.

    Args:
        goals: Loaded goals config (from load_goals).
        usage: Output from scrape_usage (for current week).
        skills_data: Output from scrape_skills.
        trouble_spots: Output from scrape_trouble_spots.
        day_of_week: Override for testing (1=Mon, 7=Sun). Auto-detected if None.

    Returns dict with week_start, day_of_week, and per-metric status.
    """
    today = date.today()
    if day_of_week is None:
        day_of_week = today.isoweekday()  # 1=Mon, 7=Sun

    # Compute week start (Monday)
    week_start = today - timedelta(days=today.weekday())

    weekly = goals.get("weekly", {})

    # Gather actuals
    actual_time = usage.get("time_spent_min", 0)
    actual_questions = usage.get("questions_answered", 0)
    actual_days = usage.get("days_active", 0)

    # Count mastered skills (90+)
    actual_mastered = 0
    for subj in skills_data:
        for sk in subj.get("skills", []):
            if (sk.get("smart_score", 0) or 0) >= 90:
                actual_mastered += 1

    # Trouble spots: count current (lower is better, so we track reduction)
    actual_trouble_reduced = 0  # Can't compute without baseline; default to 0

    metrics = {}
    for key, actual, target in [
        ("time_min", actual_time, weekly.get("time_min", 0)),
        ("questions", actual_questions, weekly.get("questions", 0)),
        ("skills_mastered", actual_mastered, weekly.get("skills_mastered", 0)),
        ("days_active", actual_days, weekly.get("days_active", 0)),
        ("trouble_spots_reduced", actual_trouble_reduced, weekly.get("trouble_spots_reduced", 0)),
    ]:
        pct = int(actual / target * 100) if target > 0 else 0
        status = _compute_status(actual, target, day_of_week)
        metrics[key] = {
            "target": target,
            "actual": actual,
            "status": status,
            "pct": pct,
        }

    return {
        "week_start": week_start.isoformat(),
        "day_of_week": day_of_week,
        "metrics": metrics,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals.py::TestEvaluateGoals -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/goals.py tests/test_goals.py
git commit -m "feat(goals): add goal evaluation with status computation"
```

---

### Task 4: Add `ixl goals` CLI command

**Files:**
- Modify: `ixl_cli/cli.py`

- [ ] **Step 1: Add output_goals formatter and cmd_goals to cli.py**

Add import at top of `cli.py` (after existing scraper imports):
```python
from ixl_cli.goals import evaluate_goals, generate_defaults, load_goals, save_goals
from ixl_cli.session import GOALS_PATH
```

Add output formatter (after `output_assigned`):
```python
def output_goals(goal_status: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(goal_status, indent=2))
        return
    if not goal_status:
        print("No goal data available.")
        return

    week_start = goal_status.get("week_start", "")
    day = goal_status.get("day_of_week", 0)

    # Compute week end (Sunday)
    from datetime import timedelta
    try:
        ws = datetime.fromisoformat(week_start)
        we = ws + timedelta(days=6)
        header = f"  Weekly Goals ({ws.strftime('%a %b %d')} - {we.strftime('%a %b %d')})"
    except (ValueError, TypeError):
        header = "  Weekly Goals"

    print(f"\n{header}")
    print(f"  Day {day} of 7\n")

    labels = {
        "time_min": "Time spent",
        "questions": "Questions",
        "skills_mastered": "Skills mastered",
        "days_active": "Days active",
        "trouble_spots_reduced": "Trouble spots",
    }
    units = {
        "time_min": "min",
        "trouble_spots_reduced": "reduced",
    }

    metrics = goal_status.get("metrics", {})
    for key, label in labels.items():
        m = metrics.get(key)
        if not m:
            continue
        target = m["target"]
        actual = m["actual"]
        status = m["status"]
        pct = m["pct"]
        unit = units.get(key, "")
        suffix = f" {unit}" if unit else ""

        # Progress bar (10 chars)
        filled = min(10, int(pct / 10))
        bar = "=" * filled + "-" * (10 - filled)

        print(f"    {label:<18} {actual:>4} / {target:<4}{suffix:<8} [{bar}]  {status}")

    print()
```

Add command function (after `cmd_assigned`):
```python
def cmd_goals(args: argparse.Namespace) -> None:
    if args.init:
        session = IXLSession(verbose=True)
        _log("Generating goal defaults from last 14 days of usage...", True)

        usage = scrape_usage(session, days=14)
        skills_data = scrape_skills(session)
        defaults = generate_defaults(usage, skills_data)
        save_goals(defaults)

        print(f"\nGoals saved to {GOALS_PATH}")
        print(json.dumps(defaults, indent=2))
        print(f"\nEdit {GOALS_PATH} to adjust targets.")
        return

    goals = load_goals()
    if goals is None:
        print("No goals configured. Run `ixl goals --init`.")
        return

    session = IXLSession(verbose=not args.json)

    # Fetch current week's data (days since Monday)
    from datetime import timedelta
    today = datetime.now()
    days_since_monday = today.weekday()  # 0=Mon
    usage = scrape_usage(session, days=days_since_monday + 1)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)

    goal_status = evaluate_goals(goals, usage, skills_data, trouble_spots)
    output_goals(goal_status, args.json)
```

- [ ] **Step 2: Add goals subparser to main()**

Add after the `sp_sum` block in `main()`:
```python
    # ixl goals
    sp_goals = subparsers.add_parser("goals", help="Weekly goal tracking")
    sp_goals.add_argument("--init", action="store_true", help="Generate goals from recent usage")
    sp_goals.add_argument("--json", action="store_true", help="JSON output")
    sp_goals.set_defaults(func=cmd_goals)
```

- [ ] **Step 3: Run all tests to verify nothing broke**

Run: `python -m pytest tests/ -v`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add ixl_cli/cli.py
git commit -m "feat(goals): add ixl goals CLI command with --init and --json"
```

---

### Task 5: Embed goals in summary output

**Files:**
- Modify: `ixl_cli/cli.py` (cmd_summary and output_summary)

- [ ] **Step 1: Update cmd_summary to fetch and include goals**

In `cmd_summary`, add after the existing scraper calls:
```python
    # Goals (optional — only if configured)
    goals = load_goals()
    goal_status = None
    if goals is not None:
        from datetime import timedelta as td
        days_since_monday = datetime.now().weekday()
        week_usage = scrape_usage(session, days=days_since_monday + 1)
        goal_status = evaluate_goals(goals, week_usage, skills_data, trouble_spots)

    output_summary(child, children, diagnostics, skills_data, trouble_spots, usage, as_json=args.json, goal_status=goal_status)
```

- [ ] **Step 2: Update output_summary signature and add goals section**

Update `output_summary` to accept `goal_status`:
```python
def output_summary(
    child: dict | None,
    children: list[dict],
    diagnostics: list[dict],
    skills_data: list[dict],
    trouble_spots: list[dict],
    usage: dict,
    as_json: bool,
    goal_status: dict | None = None,
) -> None:
    if as_json:
        data = {
            "student": child,
            "timestamp": datetime.now().isoformat(),
            "diagnostics": diagnostics,
            "skills": skills_data,
            "trouble_spots": trouble_spots,
            "usage": usage,
        }
        if goal_status is not None:
            data["goals"] = goal_status
        print(json.dumps(data, indent=2))
        return

    name = child["name"] if child else "Student"
    print(f"\n{'=' * 60}")
    print(f"  IXL Summary for: {name}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    print("\n--- Diagnostics ---")
    output_diagnostics(diagnostics, False)

    print("\n--- Skills ---")
    output_skills(skills_data, False)

    print("\n--- Trouble Spots ---")
    output_trouble_spots(trouble_spots, False)

    print("\n--- Usage ---")
    output_usage(usage, False)

    if goal_status is not None:
        print("\n--- Goals ---")
        output_goals(goal_status, False)
```

- [ ] **Step 3: Run all tests to verify nothing broke**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add ixl_cli/cli.py
git commit -m "feat(goals): embed goal status in ixl summary output"
```

---

### Task 6: Final integration test and push

**Files:**
- All

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (21 existing + 11 new = 32 total)

- [ ] **Step 2: Verify CLI help includes goals**

Run: `python -m ixl_cli goals --help`
Expected: Shows `--init` and `--json` flags

- [ ] **Step 3: Push**

```bash
git push origin main
```
