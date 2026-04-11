from ixl_cli.session import ACCOUNTS_PATH, IXL_DIR

def test_accounts_path_is_under_ixl_dir():
    assert ACCOUNTS_PATH == IXL_DIR / "accounts.env"
