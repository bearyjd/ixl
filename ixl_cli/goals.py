"""
IXL goal tracking — weekly targets and progress evaluation.

Goals are stored in ~/.ixl/goals.json and evaluated against
current week's scraper data.
"""

import json
import math
import os

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
