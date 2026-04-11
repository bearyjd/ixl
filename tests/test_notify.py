from ixl_cli.session import NOTIFICATIONS_PATH, IXL_DIR


def test_notifications_path_is_under_ixl_dir():
    assert NOTIFICATIONS_PATH == IXL_DIR / "notifications.json"
