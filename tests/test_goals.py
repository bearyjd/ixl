"""Tests for ixl_cli.goals."""

import json
from unittest.mock import patch



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

        with patch("ixl_cli.goals.GOALS_PATH", goals_path):
            save_goals(goals_data)
            result = load_goals()

        assert result == goals_data

    def test_goals_file_permissions(self, tmp_ixl_dir):
        """Goals file created with 0o600 permissions."""
        from ixl_cli.goals import save_goals

        goals_path = tmp_ixl_dir / "goals.json"

        with patch("ixl_cli.goals.GOALS_PATH", goals_path):
            save_goals({"weekly": {"time_min": 60}})

        mode = oct(goals_path.stat().st_mode & 0o777)
        assert mode == "0o600"


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
