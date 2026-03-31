# Goal Tracking & Alerts — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Overview

Let parents set weekly targets for IXL practice and see progress vs goals. Goals are stored in `~/.ixl/goals.json`, generated with smart defaults from recent usage, and surfaced via `ixl goals` (standalone) and `ixl summary --json` (embedded).

## Config

**File:** `~/.ixl/goals.json` (created by `ixl goals --init`, hand-editable)

```json
{
  "weekly": {
    "time_min": 150,
    "questions": 300,
    "skills_mastered": 3,
    "days_active": 5,
    "trouble_spots_reduced": 2
  }
}
```

**Permissions:** Created with `os.open` at `0o600`, consistent with other config files.

## Metrics

| Metric | What it measures | Floor default |
|--------|-----------------|---------------|
| `time_min` | Minutes of practice per week | 60 |
| `questions` | Questions answered per week | 100 |
| `skills_mastered` | New 90+ SmartScores per week | 1 |
| `days_active` | Days with any practice per week | 3 |
| `trouble_spots_reduced` | Fewer trouble spots than last week | 1 |

## Smart Defaults (`ixl goals --init`)

Fetches 14 days of usage data and computes:
- `time_min`: average weekly time, rounded up to nearest 10, floor 60
- `questions`: average weekly questions, rounded up to nearest 50, floor 100
- `skills_mastered`: weekly average of new 90+ skills, floor 1
- `days_active`: weekly average active days, floor 3
- `trouble_spots_reduced`: always 1

Output: prints generated defaults and file path. User edits file to adjust.

## Status Evaluation

Each metric gets a status computed by comparing actual progress against the weekly target, prorated by day-of-week (Monday = day 1):

- **ahead**: actual >= target * (day / 7) * 1.2 (20% buffer)
- **on_track**: actual >= target * (day / 7) * 0.8 (within 20%)
- **behind**: actual < target * (day / 7) * 0.8
- **no_data**: API failure or metric unavailable

Special case: `days_active` and `skills_mastered` are integers — use ceiling for expected pace.

Special case: `trouble_spots_reduced` compares current trouble spot count against last week's count (requires storing last week's count; falls back to `no_data` if unavailable).

## CLI Commands

### `ixl goals --init`

1. Fetch 14-day usage via `scrape_usage(session, days=14)`
2. Fetch current skills via `scrape_skills(session)` (for mastered count)
3. Compute smart defaults
4. Write `~/.ixl/goals.json` with `os.open` 0o600
5. Print defaults and file path

### `ixl goals [--json]`

1. Load `~/.ixl/goals.json` (exit with message if missing)
2. Fetch current week's data: usage (days since Monday), skills, trouble spots
3. Evaluate each metric
4. Output human-readable progress bars or JSON

### `ixl summary [--json]`

When `goals.json` exists, the summary JSON output gains a `"goals"` key containing the same structure as `ixl goals --json`. When `goals.json` does not exist, the key is omitted.

Human-readable summary gains a "Goals" section at the end, same as standalone.

## JSON Output Structure

```json
{
  "week_start": "2026-03-23",
  "day_of_week": 1,
  "metrics": {
    "time_min": {"target": 150, "actual": 45, "status": "on_track", "pct": 30},
    "questions": {"target": 300, "actual": 80, "status": "behind", "pct": 26},
    "skills_mastered": {"target": 3, "actual": 1, "status": "on_track", "pct": 33},
    "days_active": {"target": 5, "actual": 2, "status": "on_track", "pct": 40},
    "trouble_spots_reduced": {"target": 2, "actual": 0, "status": "behind", "pct": 0}
  }
}
```

## Human-Readable Output

```
  Weekly Goals (Mon Mar 23 - Sun Mar 29)
  Day 1 of 7

    Time spent:       45 / 150 min    [===-------]  on track
    Questions:        80 / 300        [==--------]  behind
    Skills mastered:   1 / 3          [===-------]  on track
    Days active:       2 / 5          [===-------]  on track
    Trouble spots:     0 / 2 reduced  [----------]  behind
```

## Architecture

### New file: `ixl_cli/goals.py`

Contains all goal logic:

- `load_goals() -> dict | None` — load from `~/.ixl/goals.json`, return None if missing
- `save_goals(goals: dict) -> None` — atomic write with 0o600
- `generate_defaults(usage: dict, skills_data: list, trouble_spots: list) -> dict` — compute smart defaults from scraper output
- `evaluate_goals(goals: dict, usage: dict, skills_data: list, trouble_spots: list) -> dict` — compute status for each metric, return the JSON output structure

### Modified files

- `cli.py` — add `goals` subcommand (with `--init` and `--json` flags), add goals section to `cmd_summary` and `output_summary`
- `session.py` — add `GOALS_PATH = IXL_DIR / "goals.json"` constant

## Error Handling

- No `goals.json` + `ixl goals`: print "No goals configured. Run `ixl goals --init`." and exit 0
- No `goals.json` + `ixl summary --json`: omit `"goals"` key, no error
- API failure during `--init`: print error, don't write partial config
- API failure during evaluation: affected metric gets `"status": "no_data"`
- Malformed `goals.json`: print warning, treat as missing

## Testing (`tests/test_goals.py`)

- `test_generate_defaults_from_usage` — verify smart defaults computation with sample data
- `test_generate_defaults_floors` — verify minimum values enforced
- `test_evaluate_on_track` — verify on_track status with proportional progress
- `test_evaluate_behind` — verify behind status
- `test_evaluate_ahead` — verify ahead status
- `test_goals_json_roundtrip` — write and read back config
- `test_missing_goals_returns_none` — load_goals returns None when file missing
- `test_malformed_goals_returns_none` — load_goals returns None on bad JSON
