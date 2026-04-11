from unittest.mock import patch

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
