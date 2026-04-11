"""Tests for ixl_cli.cli."""

import json
import os
from argparse import Namespace
from unittest.mock import call, patch

import pytest

from ixl_cli.cli import cmd_compare, cmd_init, cmd_notify, cmd_summary, finalize_result, render_json_result, summarize_result
from ixl_cli.session import _load_env_file, load_config


def test_cmd_compare_returns_setup_error_when_accounts_missing():
    with patch("ixl_cli.cli._load_accounts", return_value=[]):
        result = cmd_compare(Namespace(json=True))

    assert result["status"] == "error"
    assert result["exit_code"] == 2
    assert result["errors"][0]["code"] == "compare.accounts_missing"


def test_cmd_notify_returns_setup_error_when_config_missing():
    with patch("ixl_cli.cli._load_notify_config", return_value=None):
        result = cmd_notify(Namespace(json=True, dry_run=False))

    assert result["status"] == "error"
    assert result["exit_code"] == 2
    assert result["errors"][0]["code"] == "notify.config_missing"


def test_cmd_compare_returns_warning_when_one_account_fails():
    accounts = [
        {"name": "ford", "email": "ford@school", "password": "pw1"},
        {"name": "maya", "email": "maya@school", "password": "pw2"},
    ]

    children_results = [
        [{"name": "Ford", "grade": "3"}],
        RuntimeError("boom"),
    ]

    def fake_scrape_children(_session):
        value = children_results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    with (
        patch("ixl_cli.cli._load_accounts", return_value=accounts),
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", side_effect=fake_scrape_children),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli._build_comparison", return_value={
            "children": [{
                "name": "Ford",
                "grade": "3",
                "skills_summary": {"mastered": 0, "excellent": 0, "total": 0},
                "trouble_spot_count": 0,
                "usage": {"time_spent_min": 0, "questions_answered": 0, "days_active": 0},
            }]
        }),
        patch("builtins.print"),
    ):
        result = cmd_compare(Namespace(json=True))

    assert result["status"] == "warning"
    assert result["exit_code"] == 0
    assert result["data"]["children"] == [{
        "name": "Ford",
        "grade": "3",
        "skills_summary": {"mastered": 0, "excellent": 0, "total": 0},
        "trouble_spot_count": 0,
        "usage": {"time_spent_min": 0, "questions_answered": 0, "days_active": 0},
    }]
    assert result["warnings"][0]["code"] == "compare.account_failed"


def test_cmd_notify_returns_warning_when_one_delivery_fails():
    notify_results = [
        {"url": "https://ok", "format": "slack", "sent": True},
        {"url": "https://bad", "format": "plain", "sent": False},
    ]

    with (
        patch("ixl_cli.cli._load_notify_config", return_value={"webhooks": [{}, {}]}),
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.cli._notify_all", return_value=notify_results),
    ):
        result = cmd_notify(Namespace(json=False, dry_run=False))

    assert result["status"] == "warning"
    assert result["exit_code"] == 0
    assert result["data"] == {"results": notify_results}
    assert result["warnings"][0]["code"] == "notify.delivery_failed"


def test_cmd_notify_returns_error_when_all_deliveries_fail():
    notify_results = [
        {"url": "https://bad1", "format": "slack", "sent": False},
        {"url": "https://bad2", "format": "plain", "sent": False},
    ]

    with (
        patch("ixl_cli.cli._load_notify_config", return_value={"webhooks": [{}, {}]}),
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.cli._notify_all", return_value=notify_results),
    ):
        result = cmd_notify(Namespace(json=False, dry_run=False))

    assert result["status"] == "error"
    assert result["exit_code"] == 1
    assert result["errors"][0]["code"] == "notify.all_deliveries_failed"


def test_load_config_raises_runtime_error_when_credentials_missing(monkeypatch, tmp_ixl_dir):
    monkeypatch.delenv("IXL_EMAIL", raising=False)
    monkeypatch.delenv("IXL_PASSWORD", raising=False)

    with patch("ixl_cli.session.ENV_PATH", tmp_ixl_dir / ".env"):
        with pytest.raises(RuntimeError, match="No credentials found"):
            load_config()


def test_main_returns_exit_code_2_for_missing_credentials(monkeypatch, tmp_ixl_dir, capsys):
    monkeypatch.delenv("IXL_EMAIL", raising=False)
    monkeypatch.delenv("IXL_PASSWORD", raising=False)

    with (
        patch("ixl_cli.session.ENV_PATH", tmp_ixl_dir / ".env"),
        patch("sys.argv", ["ixl", "children", "--json"]),
    ):
        with pytest.raises(SystemExit) as exc:
            from ixl_cli.cli import main
            main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exc.value.code == 2
    assert payload["status"] == "error"
    assert payload["errors"][0]["message"].startswith("No credentials found")


def test_main_returns_exit_code_2_for_missing_goals_config(capsys):
    with (
        patch("sys.argv", ["ixl", "goals", "--json"]),
        patch("ixl_cli.cli.load_goals", return_value=None),
    ):
        with pytest.raises(SystemExit) as exc:
            from ixl_cli.cli import main
            main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exc.value.code == 2
    assert payload["status"] == "error"
    assert payload["errors"][0]["code"] == "goals.config_missing"


def test_cmd_summary_returns_normalized_data():
    with (
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={"time_spent_min": 12}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("builtins.print"),
    ):
        result = cmd_summary(Namespace(json=True, child=None, format=None, no_save=False))

    assert result["status"] == "ok"
    assert result["exit_code"] == 0
    assert result["data"]["student"] == {"name": "Ford", "grade": "3"}
    assert result["data"]["usage"] == {"time_spent_min": 12}
    assert "goals" not in result["data"]


def test_main_accepts_notify_and_compare_commands():
    with patch("sys.argv", ["ixl", "notify", "--dry-run", "--json"]):
        from ixl_cli.cli import main
        with pytest.raises(SystemExit) as exc:
            with patch("ixl_cli.cli.cmd_notify", return_value={
                "status": "ok",
                "warnings": [],
                "errors": [],
                "data": {"results": []},
                "exit_code": 0,
            }):
                main()
    assert exc.value.code == 0

    with patch("sys.argv", ["ixl", "compare", "--json"]):
        from ixl_cli.cli import main
        with pytest.raises(SystemExit) as exc:
            with patch("ixl_cli.cli.cmd_compare", return_value={
                "status": "ok",
                "warnings": [],
                "errors": [],
                "data": {"children": []},
                "exit_code": 0,
            }):
                main()
    assert exc.value.code == 0


def test_render_json_result_wraps_existing_payload_with_status_metadata():
    payload = {"student": {"name": "Ford"}, "skills": []}
    result = {
        "status": "ok",
        "warnings": [],
        "errors": [],
        "data": payload,
        "exit_code": 0,
    }

    rendered = render_json_result(result)

    assert rendered["status"] == "ok"
    assert rendered["warnings"] == []
    assert rendered["errors"] == []
    assert rendered["student"] == {"name": "Ford"}
    assert rendered["skills"] == []


def test_summarize_result_uses_warning_count_for_partial_success():
    result = {
        "status": "warning",
        "warnings": [{"code": "summary.usage_failed", "message": "Usage failed", "stage": "usage", "retryable": True}],
        "errors": [],
        "summary": None,
    }

    assert summarize_result(result) == "Completed with warnings (1)."


def test_finalize_result_prints_json_envelope(capsys):
    result = {
        "status": "ok",
        "warnings": [],
        "errors": [],
        "data": {"student": {"name": "Ford"}},
        "exit_code": 0,
    }

    exit_code = finalize_result(result, as_json=True)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {
        "status": "ok",
        "warnings": [],
        "errors": [],
        "student": {"name": "Ford"},
    }


def test_finalize_result_prints_warning_summary_and_details(capsys):
    result = {
        "status": "warning",
        "warnings": [{"code": "compare.account_failed", "message": "Failed to fetch data for ford", "stage": "compare", "retryable": True}],
        "errors": [],
        "data": {},
        "exit_code": 0,
        "summary": None,
    }

    exit_code = finalize_result(result, as_json=False)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Completed with warnings (1)." in captured.out
    assert "Warning [compare]: Failed to fetch data for ford" in captured.err


class TestPasswordEcho:
    """Bug #4: Password entered via input() — no terminal masking."""

    def test_init_uses_getpass_for_password(self, tmp_ixl_dir):
        """cmd_init should use getpass.getpass for password, not input."""
        env_path = tmp_ixl_dir / ".env"

        with (
            patch("ixl_cli.cli.ENV_PATH", env_path),
            patch("ixl_cli.cli.IXL_DIR", tmp_ixl_dir),
            patch("ixl_cli.cli._ensure_dir"),
            patch("builtins.input", side_effect=["testuser@school", ""]),
            patch("ixl_cli.cli.getpass.getpass", return_value="secret123") as mock_getpass,
        ):
            cmd_init(Namespace())

        mock_getpass.assert_called_once()
        assert env_path.exists()
        content = env_path.read_text()
        assert "secret123" in content


class TestEnvSpecialChars:
    """Bug #7: .env injection with special characters in password."""

    @pytest.mark.parametrize("password", [
        'pass"word',
        "pass\\word",
        "pass$word",
        'p@ss"w\\o$rd!',
        '"startsWithQuote',
        'has\nnewline',
    ])
    def test_special_chars_roundtrip(self, tmp_ixl_dir, password):
        """Passwords with special chars should survive write-then-read."""
        env_path = tmp_ixl_dir / ".env"

        with (
            patch("ixl_cli.cli.ENV_PATH", env_path),
            patch("ixl_cli.cli.IXL_DIR", tmp_ixl_dir),
            patch("ixl_cli.cli._ensure_dir"),
            patch("builtins.input", side_effect=["testuser@school", ""]),
            patch("ixl_cli.cli.getpass.getpass", return_value=password),
        ):
            cmd_init(Namespace())

        parsed = _load_env_file(env_path)
        assert parsed["IXL_PASSWORD"] == password, (
            f"Password roundtrip failed: wrote {password!r}, read {parsed['IXL_PASSWORD']!r}"
        )


class TestCredentialFilePermissions:
    """Bug #10: TOCTOU race on credential file creation."""

    def test_env_file_created_with_600_permissions(self, tmp_ixl_dir):
        """Credential file should be created with 0o600 from the start."""
        env_path = tmp_ixl_dir / ".env"

        with (
            patch("ixl_cli.cli.ENV_PATH", env_path),
            patch("ixl_cli.cli.IXL_DIR", tmp_ixl_dir),
            patch("ixl_cli.cli._ensure_dir"),
            patch("builtins.input", side_effect=["testuser@school", ""]),
            patch("ixl_cli.cli.getpass.getpass", return_value="secret123"),
        ):
            cmd_init(Namespace())

        mode = oct(env_path.stat().st_mode & 0o777)
        assert mode == "0o600", f"Expected 0o600, got {mode}"
