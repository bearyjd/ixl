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
