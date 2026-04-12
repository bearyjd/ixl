# History & Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daily snapshot saving on `ixl summary` and an `ixl trends` command that shows SmartScore/trouble-spot deltas over time.

**Architecture:** `ixl_cli/history.py` owns snapshot I/O and trend computation. `cmd_summary` auto-saves after fetching unless `--no-save` is given. A new `ixl trends` command reads those snapshots and returns deltas. `evaluate_goals` in `goals.py` gains a `trouble_spot_baseline` parameter so the previously-zeroed `trouble_spots_reduced` metric can report correctly.

**Tech Stack:** Python stdlib only — `json`, `os`, `pathlib`, `datetime`. Same atomic-write pattern as `goals.py`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `ixl_cli/history.py` | Create | Snapshot save/load/compute |
| `ixl_cli/session.py` | Modify (line 29–31) | Add `SNAPSHOTS_DIR` path constant |
| `ixl_cli/goals.py` | Modify (line 56–96) | Add `trouble_spot_baseline` param to `evaluate_goals` |
| `ixl_cli/cli.py` | Modify (multiple) | Wire `--no-save`, add `ixl trends` subcommand |
| `tests/test_history.py` | Create | All history tests |

---

### Task 1: Add SNAPSHOTS_DIR constant to session.py

**Files:**
- Modify: `ixl_cli/session.py:28-31`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_history.py
from ixl_cli.session import SNAPSHOTS_DIR, IXL_DIR

def test_snapshots_dir_is_under_ixl_dir():
    assert SNAPSHOTS_DIR == IXL_DIR / "snapshots"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_history.py::test_snapshots_dir_is_under_ixl_dir -v`
Expected: FAIL with `ImportError: cannot import name 'SNAPSHOTS_DIR'`

- [ ] **Step 3: Add constant to session.py**

In `ixl_cli/session.py`, after line 31 (`GOALS_PATH = IXL_DIR / "goals.json"`), add:

```python
SNAPSHOTS_DIR = IXL_DIR / "snapshots"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_history.py::test_snapshots_dir_is_under_ixl_dir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/session.py tests/test_history.py
git commit -m "feat(history): add SNAPSHOTS_DIR path constant"
```

---

### Task 2: Implement save_snapshot in history.py

**Files:**
- Create: `ixl_cli/history.py`
- Modify: `tests/test_history.py`

A snapshot is a compact summary of the student's current state, saved daily. Snapshot structure:
```json
{
  "date": "2026-04-11",
  "skills_mastered": 12,
  "skills_excellent": 5,
  "trouble_spot_count": 8,
  "time_spent_min": 45,
  "questions_answered": 120,
  "days_active": 3
}
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_history.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch
from ixl_cli.history import save_snapshot

def test_save_snapshot_writes_file(tmp_path):
    data = {
        "date": "2026-04-11",
        "skills_mastered": 12,
        "skills_excellent": 5,
        "trouble_spot_count": 8,
        "time_spent_min": 45,
        "questions_answered": 120,
        "days_active": 3,
    }
    snapshots_dir = tmp_path / "snapshots"
    with patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir):
        save_snapshot(data)
    path = snapshots_dir / "2026-04-11.json"
    assert path.exists()
    assert json.loads(path.read_text()) == data

def test_save_snapshot_has_600_permissions(tmp_path):
    data = {"date": "2026-04-11", "skills_mastered": 0, "skills_excellent": 0,
            "trouble_spot_count": 0, "time_spent_min": 0, "questions_answered": 0, "days_active": 0}
    snapshots_dir = tmp_path / "snapshots"
    with patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir):
        save_snapshot(data)
    path = snapshots_dir / "2026-04-11.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"

def test_save_snapshot_overwrites_same_day(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    data1 = {"date": "2026-04-11", "skills_mastered": 10, "skills_excellent": 2,
              "trouble_spot_count": 5, "time_spent_min": 30, "questions_answered": 80, "days_active": 2}
    data2 = {**data1, "skills_mastered": 11}
    with patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir):
        save_snapshot(data1)
        save_snapshot(data2)
    path = snapshots_dir / "2026-04-11.json"
    assert json.loads(path.read_text())["skills_mastered"] == 11
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -k "save_snapshot" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ixl_cli.history'`

- [ ] **Step 3: Implement history.py with save_snapshot**

Create `ixl_cli/history.py`:

```python
"""
IXL history — daily snapshots and trend computation.

Snapshots are saved to ~/.ixl/snapshots/YYYY-MM-DD.json each time
`ixl summary` runs (unless --no-save is given).
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from ixl_cli.session import SNAPSHOTS_DIR


def _build_snapshot(
    skills_data: list,
    trouble_spots: list,
    usage: dict,
    today: date | None = None,
) -> dict:
    """Distill raw scraper output into a compact daily snapshot."""
    if today is None:
        today = date.today()

    mastered = 0
    excellent = 0
    for subj in skills_data:
        for sk in subj.get("skills", []):
            score = sk.get("smart_score", 0) or 0
            if score >= 90:
                mastered += 1
            elif score >= 80:
                excellent += 1

    return {
        "date": today.isoformat(),
        "skills_mastered": mastered,
        "skills_excellent": excellent,
        "trouble_spot_count": len(trouble_spots),
        "time_spent_min": usage.get("time_spent_min", 0),
        "questions_answered": usage.get("questions_answered", 0),
        "days_active": usage.get("days_active", 0),
    }


def save_snapshot(data: dict) -> None:
    """Atomic write snapshot to ~/.ixl/snapshots/YYYY-MM-DD.json (0o600)."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{data['date']}.json"
    tmp_path = path.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(str(tmp_path), str(path))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -k "save_snapshot" -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/history.py ixl_cli/session.py tests/test_history.py
git commit -m "feat(history): implement save_snapshot with atomic write"
```

---

### Task 3: Implement load_snapshots and _build_snapshot helper

**Files:**
- Modify: `ixl_cli/history.py`
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_history.py`:

```python
import json
from unittest.mock import patch
from ixl_cli.history import load_snapshots, _build_snapshot

def test_load_snapshots_returns_last_n_days(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    for i, day in enumerate(["2026-04-09", "2026-04-10", "2026-04-11"]):
        path = snapshots_dir / f"{day}.json"
        fd = __import__("os").open(str(path), __import__("os").O_WRONLY | __import__("os").O_CREAT | __import__("os").O_TRUNC, 0o600)
        with __import__("os").fdopen(fd, "w") as f:
            json.dump({"date": day, "skills_mastered": i}, f)
    with patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir):
        result = load_snapshots(days=2)
    assert len(result) == 2
    assert result[0]["date"] == "2026-04-10"
    assert result[1]["date"] == "2026-04-11"

def test_load_snapshots_returns_empty_when_none(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    with patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir):
        result = load_snapshots(days=7)
    assert result == []

def test_build_snapshot_counts_mastered_and_excellent():
    skills_data = [
        {"skills": [
            {"smart_score": 92}, {"smart_score": 85}, {"smart_score": 91},
            {"smart_score": 60}, {"smart_score": None},
        ]}
    ]
    from datetime import date
    snap = _build_snapshot(skills_data, trouble_spots=[{}, {}], usage={"time_spent_min": 30, "questions_answered": 100, "days_active": 2}, today=date(2026, 4, 11))
    assert snap["skills_mastered"] == 2
    assert snap["skills_excellent"] == 1
    assert snap["trouble_spot_count"] == 2
    assert snap["date"] == "2026-04-11"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -k "load_snapshots or build_snapshot" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add load_snapshots to history.py**

Add to `ixl_cli/history.py` (after `save_snapshot`):

```python
def load_snapshots(days: int = 30) -> list[dict]:
    """Load the last `days` daily snapshots, sorted oldest-first.

    Returns an empty list if no snapshots exist.
    """
    if not SNAPSHOTS_DIR.exists():
        return []

    today = date.today()
    result = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        path = SNAPSHOTS_DIR / f"{day.isoformat()}.json"
        if path.exists():
            try:
                with open(path) as f:
                    result.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass  # skip corrupt snapshots silently
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -k "load_snapshots or build_snapshot" -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/history.py tests/test_history.py
git commit -m "feat(history): add load_snapshots and _build_snapshot helper"
```

---

### Task 4: Implement compute_trends

**Files:**
- Modify: `ixl_cli/history.py`
- Modify: `tests/test_history.py`

`compute_trends` returns a dict with `datapoints` (the raw snapshots) and `deltas` (oldest→newest change for each metric).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_history.py`:

```python
from ixl_cli.history import compute_trends

def test_compute_trends_returns_deltas():
    snapshots = [
        {"date": "2026-04-10", "skills_mastered": 10, "skills_excellent": 4,
         "trouble_spot_count": 8, "time_spent_min": 40, "questions_answered": 100, "days_active": 3},
        {"date": "2026-04-11", "skills_mastered": 12, "skills_excellent": 5,
         "trouble_spot_count": 6, "time_spent_min": 50, "questions_answered": 130, "days_active": 4},
    ]
    result = compute_trends(snapshots)
    assert result["deltas"]["skills_mastered"] == 2
    assert result["deltas"]["trouble_spot_count"] == -2
    assert result["deltas"]["time_spent_min"] == 10
    assert len(result["datapoints"]) == 2

def test_compute_trends_returns_empty_when_no_snapshots():
    result = compute_trends([])
    assert result == {"datapoints": [], "deltas": {}}

def test_compute_trends_returns_empty_deltas_for_single_snapshot():
    snapshots = [{"date": "2026-04-11", "skills_mastered": 10, "skills_excellent": 3,
                  "trouble_spot_count": 5, "time_spent_min": 30, "questions_answered": 80, "days_active": 2}]
    result = compute_trends(snapshots)
    assert result["datapoints"] == snapshots
    assert result["deltas"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -k "compute_trends" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add compute_trends to history.py**

Add to `ixl_cli/history.py`:

```python
_TREND_METRICS = [
    "skills_mastered",
    "skills_excellent",
    "trouble_spot_count",
    "time_spent_min",
    "questions_answered",
    "days_active",
]


def compute_trends(snapshots: list[dict]) -> dict:
    """Compute deltas between oldest and newest snapshot.

    Returns:
        {
            "datapoints": [...snapshots oldest-first],
            "deltas": {"skills_mastered": 2, "trouble_spot_count": -1, ...}
        }
    """
    if not snapshots:
        return {"datapoints": [], "deltas": {}}
    if len(snapshots) == 1:
        return {"datapoints": snapshots, "deltas": {}}

    oldest = snapshots[0]
    newest = snapshots[-1]
    deltas = {
        metric: newest.get(metric, 0) - oldest.get(metric, 0)
        for metric in _TREND_METRICS
        if metric in oldest and metric in newest
    }
    return {"datapoints": snapshots, "deltas": deltas}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -k "compute_trends" -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/history.py tests/test_history.py
git commit -m "feat(history): implement compute_trends with delta computation"
```

---

### Task 5: Wire --no-save into cmd_summary

**Files:**
- Modify: `ixl_cli/cli.py:733-765` (`cmd_summary`)
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_history.py`:

```python
import sys
import json
from unittest.mock import patch, MagicMock
from argparse import Namespace

def test_cmd_summary_saves_snapshot_by_default(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    with (
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={"time_spent_min": 10, "questions_answered": 50, "days_active": 2}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir),
        patch("builtins.print"),
    ):
        from ixl_cli.cli import cmd_summary
        cmd_summary(Namespace(json=True, child=None, format=None, no_save=False))
    assert any(snapshots_dir.glob("*.json")), "Expected snapshot to be saved"

def test_cmd_summary_skips_snapshot_when_no_save(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    with (
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir),
        patch("builtins.print"),
    ):
        from ixl_cli.cli import cmd_summary
        cmd_summary(Namespace(json=True, child=None, format=None, no_save=True))
    assert not snapshots_dir.exists() or not any(snapshots_dir.glob("*.json"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -k "cmd_summary_saves" -v`
Expected: FAIL — no snapshot saved

- [ ] **Step 3: Update cmd_summary in cli.py**

Add import at the top of `ixl_cli/cli.py` (after line 34):

```python
from ixl_cli.history import _build_snapshot, save_snapshot
```

Modify `cmd_summary` (replace lines 733–765) so it saves a snapshot unless `--no-save`:

```python
def cmd_summary(args: argparse.Namespace) -> dict:
    session = IXLSession(verbose=not args.json)
    children = scrape_children(session)
    child = children[0] if children else None

    diagnostics = scrape_diagnostics(session)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)
    usage = scrape_usage(session)

    # Auto-save snapshot for trend tracking (skip with --no-save)
    if not getattr(args, "no_save", False):
        save_snapshot(_build_snapshot(skills_data, trouble_spots, usage))

    # Goals (optional — only included if configured)
    goals = load_goals()
    goal_status = None
    if goals is not None:
        days_since_monday = datetime.now().weekday()
        week_usage = scrape_usage(session, days=days_since_monday + 1)
        goal_status = evaluate_goals(goals, week_usage, skills_data, trouble_spots)

    if not args.json:
        output_summary(child, children, diagnostics, skills_data, trouble_spots, usage, False, goal_status=goal_status)

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

    return make_result(command="summary", data=data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -k "cmd_summary_saves" -v`
Expected: 2 PASS

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: all 23 existing tests still PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/cli.py ixl_cli/history.py tests/test_history.py
git commit -m "feat(history): auto-save snapshot on ixl summary (--no-save skips)"
```

---

### Task 6: Add ixl trends command to CLI

**Files:**
- Modify: `ixl_cli/cli.py` (add `cmd_trends`, register subcommand)
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_history.py`:

```python
from argparse import Namespace
from unittest.mock import patch

def test_cmd_trends_returns_ok_result_with_datapoints(tmp_path):
    snapshots = [
        {"date": "2026-04-10", "skills_mastered": 10, "skills_excellent": 3,
         "trouble_spot_count": 8, "time_spent_min": 40, "questions_answered": 100, "days_active": 3},
        {"date": "2026-04-11", "skills_mastered": 12, "skills_excellent": 4,
         "trouble_spot_count": 6, "time_spent_min": 50, "questions_answered": 130, "days_active": 4},
    ]
    with patch("ixl_cli.history.SNAPSHOTS_DIR", tmp_path / "s"):
        with patch("ixl_cli.cli.load_snapshots", return_value=snapshots):
            from ixl_cli.cli import cmd_trends
            result = cmd_trends(Namespace(json=True, days=7))
    assert result["status"] == "ok"
    assert result["exit_code"] == 0
    assert "trends" in result["data"]
    assert result["data"]["trends"]["deltas"]["skills_mastered"] == 2

def test_cmd_trends_returns_warning_when_no_snapshots():
    with patch("ixl_cli.cli.load_snapshots", return_value=[]):
        from ixl_cli.cli import cmd_trends
        result = cmd_trends(Namespace(json=True, days=7))
    assert result["status"] == "warning"
    assert result["warnings"][0]["code"] == "trends.no_data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -k "cmd_trends" -v`
Expected: FAIL with `cannot import name 'cmd_trends'`

- [ ] **Step 3: Add cmd_trends and register subcommand in cli.py**

Add import at top of `ixl_cli/cli.py` (update history import line to):

```python
from ixl_cli.history import _build_snapshot, compute_trends, load_snapshots, save_snapshot
```

Add `cmd_trends` function (after `cmd_summary`, before `main`):

```python
def cmd_trends(args: argparse.Namespace) -> dict:
    """Show historical trends from saved snapshots."""
    snapshots = load_snapshots(days=args.days)
    if not snapshots:
        result = make_result(command="trends", data={"trends": {"datapoints": [], "deltas": {}}})
        add_warning(
            result,
            code="trends.no_data",
            message=f"No snapshots found for the last {args.days} days. Run `ixl summary` at least twice to build history.",
            stage="trends",
            retryable=False,
        )
        return result

    trends = compute_trends(snapshots)

    if not args.json:
        deltas = trends.get("deltas", {})
        print(f"\n  Trends (last {len(snapshots)} snapshots over {args.days} days):")
        labels = {
            "skills_mastered": "Skills mastered",
            "skills_excellent": "Skills excellent",
            "trouble_spot_count": "Trouble spots",
            "time_spent_min": "Time (min)",
            "questions_answered": "Questions answered",
            "days_active": "Days active",
        }
        for key, label in labels.items():
            if key in deltas:
                delta = deltas[key]
                sign = "+" if delta > 0 else ""
                print(f"    {label:<22} {sign}{delta}")
        print()

    return make_result(command="trends", data={"trends": trends})
```

In `main()`, add the `ixl trends` subparser (after the `ixl goals` block, before `args = parser.parse_args()`):

```python
    # ixl trends
    sp_trends = subparsers.add_parser("trends", help="Show historical progress trends")
    sp_trends.add_argument("--days", type=int, default=30, help="Days to look back (default 30)")
    sp_trends.add_argument("--json", action="store_true", help="JSON output")
    sp_trends.set_defaults(func=cmd_trends)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -k "cmd_trends" -v`
Expected: 2 PASS

Run: `python3 -m pytest -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add ixl_cli/cli.py tests/test_history.py
git commit -m "feat(history): add ixl trends command with delta output"
```

---

### Task 7: Fix trouble_spots_reduced baseline in goals.py

**Files:**
- Modify: `ixl_cli/goals.py:56-119` (`evaluate_goals`)
- Modify: `ixl_cli/cli.py:733-765` (`cmd_summary`)
- Modify: `tests/test_history.py`

`evaluate_goals` currently hardcodes `actual_trouble_reduced = 0`. Now that we have snapshots, we can look up yesterday's trouble_spot_count and compute the real reduction.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_history.py`:

```python
from ixl_cli.goals import evaluate_goals

def test_evaluate_goals_uses_trouble_spot_baseline():
    goals = {"weekly": {"time_min": 60, "questions": 100, "skills_mastered": 2, "days_active": 3, "trouble_spots_reduced": 2}}
    usage = {"time_spent_min": 70, "questions_answered": 110, "days_active": 4}
    skills_data = []
    trouble_spots = [{}] * 6  # 6 trouble spots now

    # baseline was 8 — reduction is 8-6=2
    result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=3, trouble_spot_baseline=8)
    assert result["metrics"]["trouble_spots_reduced"]["actual"] == 2
    assert result["metrics"]["trouble_spots_reduced"]["status"] in ("ok", "ahead", "on_track")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_history.py::test_evaluate_goals_uses_trouble_spot_baseline -v`
Expected: FAIL — evaluate_goals doesn't accept trouble_spot_baseline param

- [ ] **Step 3: Update evaluate_goals signature in goals.py**

In `ixl_cli/goals.py`, update `evaluate_goals` signature (line 56) to:

```python
def evaluate_goals(
    goals: dict,
    usage: dict,
    skills_data: list,
    trouble_spots: list,
    day_of_week: int | None = None,
    trouble_spot_baseline: int | None = None,
) -> dict:
```

Replace lines 95–96 (`actual_trouble_reduced = 0`) with:

```python
    # Trouble spots: compare current count to baseline (prior snapshot)
    current_trouble_count = len(trouble_spots)
    if trouble_spot_baseline is not None:
        actual_trouble_reduced = max(0, trouble_spot_baseline - current_trouble_count)
    else:
        actual_trouble_reduced = 0  # no baseline available; reported as 0
```

- [ ] **Step 4: Update cmd_summary to pass trouble_spot_baseline from yesterday's snapshot**

In `ixl_cli/cli.py`, update the goals section inside `cmd_summary`:

```python
    goals = load_goals()
    goal_status = None
    if goals is not None:
        days_since_monday = datetime.now().weekday()
        week_usage = scrape_usage(session, days=days_since_monday + 1)
        # Load yesterday's snapshot for trouble-spot baseline
        yesterday_snapshots = load_snapshots(days=1)
        trouble_baseline = yesterday_snapshots[-1]["trouble_spot_count"] if yesterday_snapshots else None
        goal_status = evaluate_goals(goals, week_usage, skills_data, trouble_spots, trouble_spot_baseline=trouble_baseline)
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `python3 -m pytest -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add ixl_cli/goals.py ixl_cli/cli.py tests/test_history.py
git commit -m "feat(goals): use snapshot baseline for trouble_spots_reduced metric"
```

---

### Task 8: Update module docstring in cli.py

**Files:**
- Modify: `ixl_cli/cli.py:1-15`

- [ ] **Step 1: Update the docstring**

Replace the `Usage:` section in `ixl_cli/cli.py:1-15` to include `trends`:

```python
"""
ixl — IXL student account CLI scraper.

Logs in via Playwright (Cloudflare-resistant), caches session cookies,
and fetches data from IXL's JSON analytics APIs.

Usage:
    ixl init                                    — set up credentials interactively
    ixl children                                — show student profile info
    ixl diagnostics [--child NAME] [--json]     — diagnostic levels per subject
    ixl skills      [--child NAME] [--subject SUBJ] [--json]  — skill scores
    ixl trouble     [--child NAME] [--json]     — trouble spots
    ixl usage       [--child NAME] [--days N] [--json]         — usage stats
    ixl summary     [--child NAME] [--no-save] [--json]        — everything in one shot
    ixl trends      [--days N] [--json]         — historical progress trends
    ixl goals       [--init] [--json]           — weekly goal tracking
    ixl compare     [--json]                    — side-by-side for all accounts.env children
    ixl notify      [--dry-run] [--json]        — send webhook notifications
"""
```

- [ ] **Step 2: Run all tests to verify nothing broke**

Run: `python3 -m pytest -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add ixl_cli/cli.py
git commit -m "docs(cli): update module docstring to include trends command"
```
