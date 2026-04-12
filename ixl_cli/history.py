"""
IXL history — daily snapshots and trend computation.

Snapshots are saved to ~/.ixl/snapshots/YYYY-MM-DD.json each time
`ixl summary` runs (unless --no-save is given).
"""

import json
import os
from datetime import date, timedelta
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


def load_snapshots(days: int = 30) -> list[dict]:
    """Load the last `days` daily snapshots, sorted oldest-first.

    Returns an empty list if no snapshots exist.
    """
    if not SNAPSHOTS_DIR.exists():
        return []

    today = date.today()
    result = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        path = SNAPSHOTS_DIR / f"{day.isoformat()}.json"
        if path.exists():
            try:
                with open(path) as f:
                    result.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass  # skip corrupt snapshots silently
    return result


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
