"""
IXL goal tracking — weekly targets and progress evaluation.

Goals are stored in ~/.ixl/goals.json and evaluated against
current week's scraper data.
"""

import json
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
