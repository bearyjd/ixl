"""Shared fixtures for IXL CLI tests."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ixl_cli.session import IXLSession


@pytest.fixture
def mock_config():
    """Minimal config dict that bypasses credential loading."""
    return {
        "email": "testuser@testschool",
        "password": "testpass",
        "username": "testuser",
        "school": "testschool",
    }


@pytest.fixture
def mock_session(mock_config):
    """IXLSession with mocked login and config — no real HTTP or Playwright."""
    with patch.object(IXLSession, "__init__", lambda self, **kw: None):
        session = IXLSession.__new__(IXLSession)
        session.s = requests.Session()
        session.cfg = mock_config
        session.verbose = False
        session._logged_in = True
        session._last_request_time = 0.0
        session._cache = {}
        yield session


@pytest.fixture
def tmp_ixl_dir(tmp_path):
    """Temporary ~/.ixl directory for testing file operations."""
    ixl_dir = tmp_path / ".ixl"
    ixl_dir.mkdir(mode=0o700)
    return ixl_dir


def make_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    # Make raise_for_status behave like the real thing
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Error", response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp
