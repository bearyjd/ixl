"""IXL historical trend tracking — daily snapshots and delta computation."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from ixl_cli.session import IXL_DIR

HISTORY_DIR = IXL_DIR / "history"
RETENTION_DAYS = 90


def _ensure_history_dir() -> None:
    """Create history directory with 0o700 if needed."""
    HISTORY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def save_snapshot(data: dict) -> None:
    """Save today's summary data as a dated snapshot."""
    _ensure_history_dir()
    today_str = date.today().isoformat()
    path = HISTORY_DIR / f"{today_str}.json"

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    _cleanup_old_snapshots()


def load_snapshot(date_str: str) -> dict | None:
    """Load a specific day's snapshot."""
    path = HISTORY_DIR / f"{date_str}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def list_snapshots(days: int = 30) -> list[str]:
    """List available snapshot dates, most recent first."""
    if not HISTORY_DIR.exists():
        return []
    cutoff = date.today() - timedelta(days=days)
    dates = []
    for f in HISTORY_DIR.glob("*.json"):
        try:
            d = date.fromisoformat(f.stem)
            if d >= cutoff:
                dates.append(f.stem)
        except ValueError:
            continue
    dates.sort(reverse=True)
    return dates


def _count_mastered(skills_data: list) -> int:
    """Count skills with SmartScore >= 90."""
    count = 0
    for subj in skills_data:
        for sk in subj.get("skills", []):
            if (sk.get("smart_score", 0) or 0) >= 90:
                count += 1
    return count


def _get_diagnostic_level(diagnostics: list, subject: str) -> str:
    """Get overall diagnostic level for a subject."""
    for d in diagnostics:
        if subject.lower() in d.get("subject", "").lower():
            return str(d.get("overall_level", ""))
    return ""


def compute_trends(days: int = 7) -> dict | None:
    """Compare today's snapshot vs N days ago.

    Returns None if insufficient data.
    """
    today_str = date.today().isoformat()
    past_date = date.today() - timedelta(days=days)

    # Find closest available snapshot to the target past date
    today_data = load_snapshot(today_str)
    if today_data is None:
        return None

    past_data = None
    for delta in [0, -1, 1, -2, 2, -3, 3]:
        check = (past_date + timedelta(days=delta)).isoformat()
        past_data = load_snapshot(check)
        if past_data is not None:
            past_date = date.fromisoformat(check)
            break

    if past_data is None:
        return None

    # Compute deltas
    before_mastered = _count_mastered(past_data.get("skills", []))
    after_mastered = _count_mastered(today_data.get("skills", []))

    before_trouble = len(past_data.get("trouble_spots", []))
    after_trouble = len(today_data.get("trouble_spots", []))

    before_usage = past_data.get("usage", {})
    after_usage = today_data.get("usage", {})

    before_time = before_usage.get("time_spent_min", 0)
    after_time = after_usage.get("time_spent_min", 0)

    before_questions = before_usage.get("questions_answered", 0)
    after_questions = after_usage.get("questions_answered", 0)

    deltas = {
        "mastered_skills": {
            "before": before_mastered, "after": after_mastered,
            "change": after_mastered - before_mastered,
        },
        "trouble_spots": {
            "before": before_trouble, "after": after_trouble,
            "change": after_trouble - before_trouble,
        },
        "time_spent_min": {
            "before": before_time, "after": after_time,
            "change": after_time - before_time,
        },
        "questions_answered": {
            "before": before_questions, "after": after_questions,
            "change": after_questions - before_questions,
        },
    }

    # Add diagnostic levels if available
    for subj in ["math", "ela"]:
        before_level = _get_diagnostic_level(past_data.get("diagnostics", []), subj)
        after_level = _get_diagnostic_level(today_data.get("diagnostics", []), subj)
        if before_level or after_level:
            try:
                change = f"{float(after_level) - float(before_level):+.1f}"
            except (ValueError, TypeError):
                change = ""
            deltas[f"diagnostic_{subj}"] = {
                "before": before_level, "after": after_level, "change": change,
            }

    return {
        "period": {"from": past_date.isoformat(), "to": today_str},
        "deltas": deltas,
    }


def _cleanup_old_snapshots() -> None:
    """Remove snapshots older than RETENTION_DAYS."""
    if not HISTORY_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    for f in HISTORY_DIR.glob("*.json"):
        try:
            d = date.fromisoformat(f.stem)
            if d < cutoff:
                f.unlink()
        except (ValueError, OSError):
            continue
