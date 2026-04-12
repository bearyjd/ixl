# tests/test_history.py
import json
import os
from argparse import Namespace
from datetime import date
from unittest.mock import patch

from ixl_cli.session import SNAPSHOTS_DIR, IXL_DIR


def test_snapshots_dir_is_under_ixl_dir():
    assert SNAPSHOTS_DIR == IXL_DIR / "snapshots"


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


from ixl_cli.history import load_snapshots, _build_snapshot


def test_load_snapshots_returns_last_n_days(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    for i, day in enumerate(["2026-04-09", "2026-04-10", "2026-04-11"]):
        path = snapshots_dir / f"{day}.json"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"date": day, "skills_mastered": i}, f)
    with (
        patch("ixl_cli.history.SNAPSHOTS_DIR", snapshots_dir),
        patch("ixl_cli.history.date") as mock_date,
    ):
        mock_date.today.return_value = date(2026, 4, 11)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
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
    snap = _build_snapshot(
        skills_data,
        trouble_spots=[{}, {}],
        usage={"time_spent_min": 30, "questions_answered": 100, "days_active": 2},
        today=date(2026, 4, 11),
    )
    assert snap["skills_mastered"] == 2
    assert snap["skills_excellent"] == 1
    assert snap["trouble_spot_count"] == 2
    assert snap["date"] == "2026-04-11"


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


from ixl_cli.goals import evaluate_goals


def test_evaluate_goals_uses_trouble_spot_baseline():
    goals = {"weekly": {"time_min": 60, "questions": 100, "skills_mastered": 2, "days_active": 3, "trouble_spots_reduced": 2}}
    usage = {"time_spent_min": 70, "questions_answered": 110, "days_active": 4}
    skills_data = []
    trouble_spots = [{}] * 6

    result = evaluate_goals(goals, usage, skills_data, trouble_spots, day_of_week=3, trouble_spot_baseline=8)
    assert result["metrics"]["trouble_spots_reduced"]["actual"] == 2
    assert result["metrics"]["trouble_spots_reduced"]["status"] in ("ok", "ahead", "on_track")
