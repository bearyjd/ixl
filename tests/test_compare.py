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
