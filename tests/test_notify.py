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
