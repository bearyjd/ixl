import os
from argparse import Namespace
from unittest.mock import patch

from ixl_cli.cli import cmd_compare
from ixl_cli.session import ACCOUNTS_PATH, IXL_DIR


def test_accounts_path_is_under_ixl_dir():
    assert ACCOUNTS_PATH == IXL_DIR / "accounts.env"


from ixl_cli.compare import load_accounts


def test_load_accounts_parses_name_email_password(tmp_path):
    accounts_file = tmp_path / "accounts.env"
    accounts_file.write_text("ford:ford@school:pw1\nmaya:maya@school:pw2\n")
    with patch("ixl_cli.compare.ACCOUNTS_PATH", accounts_file):
        result = load_accounts()
    assert result == [
        {"name": "ford", "email": "ford@school", "password": "pw1"},
        {"name": "maya", "email": "maya@school", "password": "pw2"},
    ]


def test_load_accounts_skips_comments_and_blank_lines(tmp_path):
    accounts_file = tmp_path / "accounts.env"
    accounts_file.write_text("# comment\n\nford:ford@school:pw1\n\n")
    with patch("ixl_cli.compare.ACCOUNTS_PATH", accounts_file):
        result = load_accounts()
    assert len(result) == 1
    assert result[0]["name"] == "ford"


def test_load_accounts_returns_empty_when_file_missing(tmp_path):
    with patch("ixl_cli.compare.ACCOUNTS_PATH", tmp_path / "accounts.env"):
        result = load_accounts()
    assert result == []


def test_load_accounts_skips_malformed_lines(tmp_path):
    accounts_file = tmp_path / "accounts.env"
    accounts_file.write_text("ford:ford@school:pw1\nbadline\nmaya:maya@school:pw2\n")
    with patch("ixl_cli.compare.ACCOUNTS_PATH", accounts_file):
        result = load_accounts()
    assert len(result) == 2


from ixl_cli.compare import build_comparison


def test_build_comparison_returns_children_list():
    summaries = [
        {
            "student": {"name": "Ford", "grade": "3"},
            "skills": [
                {"skills": [{"smart_score": 92}, {"smart_score": 85}, {"smart_score": 70}]},
            ],
            "trouble_spots": [{}, {}],
            "usage": {"time_spent_min": 45, "questions_answered": 120, "days_active": 3},
        }
    ]
    result = build_comparison(summaries)
    assert "children" in result
    assert len(result["children"]) == 1
    child = result["children"][0]
    assert child["name"] == "Ford"
    assert child["grade"] == "3"
    assert child["skills_summary"]["mastered"] == 1   # score >= 90
    assert child["skills_summary"]["excellent"] == 1  # score 80-89
    assert child["skills_summary"]["total"] == 3
    assert child["trouble_spot_count"] == 2
    assert child["usage"]["time_spent_min"] == 45


def test_build_comparison_handles_missing_student():
    summaries = [
        {
            "student": None,
            "skills": [],
            "trouble_spots": [],
            "usage": {},
        }
    ]
    result = build_comparison(summaries)
    child = result["children"][0]
    assert child["name"] == "Unknown"
    assert child["grade"] == ""


def test_build_comparison_returns_empty_children_for_empty_input():
    result = build_comparison([])
    assert result == {"children": []}


# ---------------------------------------------------------------------------
# cmd_compare() env-var mutation (Bug: os.environ leak, see roadmap item 3)
# ---------------------------------------------------------------------------

def test_cmd_compare_restores_env_after_loop(monkeypatch):
    """IXL_EMAIL/IXL_PASSWORD must be restored to their pre-call values
    after cmd_compare()'s account loop, success or failure."""
    monkeypatch.setenv("IXL_EMAIL", "original@school")
    monkeypatch.setenv("IXL_PASSWORD", "original-pw")

    accounts = [
        {"name": "ford", "email": "ford@school", "password": "pw1"},
        {"name": "maya", "email": "maya@school", "password": "pw2"},
    ]

    with (
        patch("ixl_cli.cli._load_accounts", return_value=accounts),
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Test Student", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("builtins.print"),
    ):
        cmd_compare(Namespace(json=True))

    assert os.environ["IXL_EMAIL"] == "original@school"
    assert os.environ["IXL_PASSWORD"] == "original-pw"


def test_cmd_compare_restores_env_when_previously_unset(monkeypatch):
    """If IXL_EMAIL/IXL_PASSWORD weren't set before the call, they must be
    unset again afterward — not left holding the last account's creds."""
    monkeypatch.delenv("IXL_EMAIL", raising=False)
    monkeypatch.delenv("IXL_PASSWORD", raising=False)

    accounts = [{"name": "ford", "email": "ford@school", "password": "pw1"}]

    with (
        patch("ixl_cli.cli._load_accounts", return_value=accounts),
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Test Student", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("builtins.print"),
    ):
        cmd_compare(Namespace(json=True))

    assert "IXL_EMAIL" not in os.environ
    assert "IXL_PASSWORD" not in os.environ


def test_cmd_compare_continues_after_one_account_fails(monkeypatch):
    """A failure on one account must not stop later accounts from being
    scraped, and must not corrupt the data collected for them."""
    monkeypatch.setenv("IXL_EMAIL", "original@school")
    monkeypatch.setenv("IXL_PASSWORD", "original-pw")

    accounts = [
        {"name": "ford", "email": "ford@school", "password": "pw1"},
        {"name": "maya", "email": "maya@school", "password": "pw2"},
    ]

    children_results = [
        RuntimeError("boom"),
        [{"name": "Test Student Maya", "grade": "4"}],
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
        patch("builtins.print"),
    ):
        result = cmd_compare(Namespace(json=True))

    assert result["status"] == "warning"
    assert result["warnings"][0]["code"] == "compare.account_failed"
    assert len(result["data"]["children"]) == 1
    assert result["data"]["children"][0]["name"] == "Test Student Maya"
    assert os.environ["IXL_EMAIL"] == "original@school"
    assert os.environ["IXL_PASSWORD"] == "original-pw"
