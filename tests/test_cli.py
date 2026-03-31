"""Tests for ixl_cli.cli."""

import os
from argparse import Namespace
from unittest.mock import patch, call

import pytest

from ixl_cli.cli import cmd_init
from ixl_cli.session import _load_env_file


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
        'pass"word',       # double quote in middle
        "pass\\word",      # backslash
        "pass$word",       # dollar sign
        'p@ss"w\\o$rd!',   # mixed special chars
        '"startsWithQuote', # starts with double quote
        'has\nnewline',    # contains newline
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
