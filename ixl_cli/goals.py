"""
IXL goal tracking — weekly targets and progress evaluation.

Goals are stored in ~/.ixl/goals.json and evaluated against
current week's scraper data.
"""

import json
import math
import os
from datetime import date, timedelta

from ixl_cli.session import GOALS_PATH, IXL_DIR, _ensure_dir


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


def _round_up_to(value: float, multiple: int) -> int:
    """Round up to the nearest multiple."""
    return int(math.ceil(value / multiple)) * multiple


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
    trouble_spot_baseline: int | None = None,
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
    current_trouble_count = len(trouble_spots)
    if trouble_spot_baseline is not None:
        actual_trouble_reduced = max(0, trouble_spot_baseline - current_trouble_count)
    else:
        actual_trouble_reduced = 0

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
            "time_min": max(60, _round_up_to(weekly_time + 1, 10)),
            "questions": max(100, _round_up_to(weekly_questions + 1, 50)),
            "skills_mastered": max(1, math.ceil(weekly_mastered)),
            "days_active": max(3, math.ceil(weekly_days)),
            "trouble_spots_reduced": 1,
        }
    }
