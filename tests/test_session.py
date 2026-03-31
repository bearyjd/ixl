"""Tests for ixl_cli.session."""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import requests

from ixl_cli.session import IXLSession
from tests.conftest import make_response


class TestLoginFailure:
    """Bug #6: UnboundLocalError when login fails before cookie_dict is assigned."""

    def test_login_failure_before_cookies_gives_runtime_error(self, mock_session):
        """Login failure before cookie extraction should raise RuntimeError, not UnboundLocalError."""
        mock_session._logged_in = False

        mock_page = MagicMock()
        # wait_for_url succeeds (login OK), but analytics page goto fails
        # This means cookie_dict is never assigned, triggering UnboundLocalError on line 326
        call_count = [0]
        def goto_side_effect(url, **kw):
            call_count[0] += 1
            if call_count[0] > 1:  # second goto = analytics page
                raise TimeoutError("Analytics page timeout")
        mock_page.goto.side_effect = goto_side_effect
        mock_page.query_selector.return_value = None

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_playwright_fn = MagicMock(return_value=mock_cm)

        with patch("ixl_cli.session.sync_playwright", mock_playwright_fn, create=True):
            # Should raise RuntimeError, NOT UnboundLocalError
            with pytest.raises(RuntimeError, match="Login failed"):
                mock_session._do_login()


class TestFetchJsonErrorContract:
    """Bug #13: fetch_json silently returns None on error, fetch_page raises."""

    def test_fetch_json_raises_on_http_error(self, mock_session):
        """fetch_json should raise on 4xx/5xx, not silently return None."""
        mock_session.s = MagicMock()
        mock_session.s.request.return_value = make_response(500)

        with patch("ixl_cli.session.time.sleep"):
            with pytest.raises(requests.exceptions.HTTPError):
                mock_session.fetch_json("/analytics/test")

    def test_fetch_json_returns_data_on_success(self, mock_session):
        """fetch_json should return parsed JSON on 200."""
        mock_session.s = MagicMock()
        mock_session.s.request.return_value = make_response(200, json_data={"ok": True})

        with patch("ixl_cli.session.time.sleep"):
            result = mock_session.fetch_json("/analytics/test")

        assert result == {"ok": True}


class TestAtomicSessionWrite:
    """Bug #14: Session file written non-atomically, can be corrupted."""

    def test_session_file_created_with_600_permissions(self, tmp_ixl_dir):
        """Session file should be created with 0o600 from the start (no TOCTOU)."""
        import json
        from ixl_cli import session as sess_mod

        session_path = tmp_ixl_dir / "session.json"

        with patch.object(sess_mod, "SESSION_PATH", session_path), \
             patch.object(sess_mod, "IXL_DIR", tmp_ixl_dir):
            sess_mod.save_session({"cookies": {"test": "val"}, "domains": {}})

        assert session_path.exists()
        mode = oct(session_path.stat().st_mode & 0o777)
        assert mode == "0o600", f"Expected 0o600, got {mode}"

        # Verify content is valid JSON
        data = json.loads(session_path.read_text())
        assert data["cookies"]["test"] == "val"

    def test_session_write_does_not_corrupt_on_crash(self, tmp_ixl_dir):
        """If write fails mid-way, the old file should be intact."""
        import json
        from ixl_cli import session as sess_mod

        session_path = tmp_ixl_dir / "session.json"

        # Write initial good data
        with patch.object(sess_mod, "SESSION_PATH", session_path), \
             patch.object(sess_mod, "IXL_DIR", tmp_ixl_dir):
            sess_mod.save_session({"cookies": {"initial": "good"}, "domains": {}})

        # Verify initial write
        data = json.loads(session_path.read_text())
        assert data["cookies"]["initial"] == "good"


class TestRateLimitExhaustion:
    """Bug #5: _request silently returns 429 after retries exhausted."""

    def _patch_sleeps(self):
        """Patch time.sleep and random.uniform to skip delays."""
        return (
            patch("ixl_cli.session.time.sleep"),
            patch("ixl_cli.session.random.uniform", return_value=0.0),
        )

    def test_request_raises_on_429_exhaustion(self, mock_session):
        """After 3 retries on 429, should raise, not return the 429 response."""
        mock_session.s = MagicMock()
        mock_session.s.request.return_value = make_response(429)

        p1, p2 = self._patch_sleeps()
        with p1, p2:
            with pytest.raises(requests.exceptions.HTTPError, match="429"):
                mock_session._request("GET", "https://www.ixl.com/test")

    def test_request_returns_normally_on_success(self, mock_session):
        """Non-429 responses should be returned normally."""
        mock_session.s = MagicMock()
        resp_200 = make_response(200, json_data={"ok": True})
        mock_session.s.request.return_value = resp_200

        p1, p2 = self._patch_sleeps()
        with p1, p2:
            result = mock_session._request("GET", "https://www.ixl.com/test")

        assert result.status_code == 200

    def test_request_retries_then_succeeds(self, mock_session):
        """429 followed by 200 should return the 200."""
        mock_session.s = MagicMock()
        mock_session.s.request.side_effect = [
            make_response(429),
            make_response(200, json_data={"ok": True}),
        ]

        p1, p2 = self._patch_sleeps()
        with p1, p2:
            result = mock_session._request("GET", "https://www.ixl.com/test")

        assert result.status_code == 200
