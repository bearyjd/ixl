import json
from unittest.mock import patch

from ixl_cli.session import NOTIFICATIONS_PATH, IXL_DIR


def test_notifications_path_is_under_ixl_dir():
    assert NOTIFICATIONS_PATH == IXL_DIR / "notifications.json"


from ixl_cli.notify import load_notify_config


def test_load_notify_config_returns_none_when_missing(tmp_path):
    with patch("ixl_cli.notify.NOTIFICATIONS_PATH", tmp_path / "notifications.json"):
        result = load_notify_config()
    assert result is None


def test_load_notify_config_returns_dict_when_valid(tmp_path):
    config = {"webhooks": [{"url": "https://hooks.slack.com/T000", "format": "slack"}]}
    path = tmp_path / "notifications.json"
    path.write_text(json.dumps(config))
    with patch("ixl_cli.notify.NOTIFICATIONS_PATH", path):
        result = load_notify_config()
    assert result == config


def test_load_notify_config_returns_none_for_malformed_json(tmp_path):
    path = tmp_path / "notifications.json"
    path.write_text("not json {{")
    with patch("ixl_cli.notify.NOTIFICATIONS_PATH", path):
        result = load_notify_config()
    assert result is None


from ixl_cli.notify import _format_plain


def test_format_plain_includes_student_name():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 30, "questions_answered": 80},
        "trouble_spots": [{}, {}],
    }
    text = _format_plain(summary, goals=None)
    assert "Ford" in text


def test_format_plain_includes_usage_stats():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 45, "questions_answered": 120},
        "trouble_spots": [],
    }
    text = _format_plain(summary, goals=None)
    assert "45" in text
    assert "120" in text


def test_format_plain_includes_goal_status_when_present():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 45, "questions_answered": 120},
        "trouble_spots": [],
    }
    goals = {
        "week_start": "2026-04-07",
        "day_of_week": 3,
        "metrics": {
            "time_min": {"target": 60, "actual": 45, "status": "on_track", "pct": 75},
        }
    }
    text = _format_plain(summary, goals=goals)
    assert "goal" in text.lower() or "on_track" in text or "75" in text


from ixl_cli.notify import _format_slack


def test_format_slack_returns_dict_with_blocks():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 45, "questions_answered": 120},
        "trouble_spots": [{}, {}],
    }
    payload = _format_slack(summary, goals=None)
    assert isinstance(payload, dict)
    assert "blocks" in payload
    assert len(payload["blocks"]) >= 1


def test_format_slack_includes_student_name_in_header():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 45, "questions_answered": 120},
        "trouble_spots": [],
    }
    payload = _format_slack(summary, goals=None)
    text = str(payload)
    assert "Ford" in text


def test_format_slack_includes_usage_numbers():
    summary = {
        "student": {"name": "Ford", "grade": "3"},
        "usage": {"time_spent_min": 99, "questions_answered": 200},
        "trouble_spots": [],
    }
    payload = _format_slack(summary, goals=None)
    text = str(payload)
    assert "99" in text
    assert "200" in text


from unittest.mock import MagicMock
from ixl_cli.notify import notify_all

_SUMMARY = {
    "student": {"name": "Ford", "grade": "3"},
    "usage": {"time_spent_min": 30, "questions_answered": 80},
    "trouble_spots": [],
}
_CONFIG = {
    "webhooks": [
        {"url": "https://hooks.slack.com/T000", "format": "slack"},
        {"url": "https://example.com/hook", "format": "plain"},
    ]
}


def test_notify_all_dry_run_returns_results_without_posting():
    results = notify_all(_CONFIG, _SUMMARY, goals=None, dry_run=True)
    assert len(results) == 2
    assert all(r["dry_run"] for r in results)
    assert all(r["sent"] for r in results)


def test_notify_all_posts_to_each_webhook():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("ixl_cli.notify.requests.post", return_value=mock_resp) as mock_post:
        results = notify_all(_CONFIG, _SUMMARY, goals=None, dry_run=False)
    assert mock_post.call_count == 2
    assert all(r["sent"] for r in results)
    assert all(not r["dry_run"] for r in results)


def test_notify_all_marks_failed_when_post_raises():
    with patch("ixl_cli.notify.requests.post", side_effect=Exception("connection refused")):
        results = notify_all(_CONFIG, _SUMMARY, goals=None, dry_run=False)
    assert all(not r["sent"] for r in results)


def test_notify_all_slack_posts_json_content_type():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("ixl_cli.notify.requests.post", return_value=mock_resp) as mock_post:
        notify_all(
            {"webhooks": [{"url": "https://hooks.slack.com/T000", "format": "slack"}]},
            _SUMMARY, goals=None, dry_run=False,
        )
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs.get("headers", {}).get("Content-Type") == "application/json"
