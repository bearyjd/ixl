"""
IXL session management — Playwright login, session caching, request wrapper.

Handles:
- Credential loading (env vars > ~/.ixl/.env)
- Login via Playwright (Cloudflare blocks raw requests)
- Cookie export from browser to requests.Session
- Session cookie caching with TTL
- Rate-limited request wrapper with exponential backoff
"""

import hashlib
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Union

import requests

# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

IXL_DIR = Path.home() / ".ixl"
ENV_PATH = IXL_DIR / ".env"
SESSION_PATH = IXL_DIR / "session.json"
GOALS_PATH = IXL_DIR / "goals.json"
ACCOUNTS_PATH = IXL_DIR / "accounts.env"

BASE_URL = "https://www.ixl.com"

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# IXL sessions are shorter-lived; conservative 60 min TTL.
SESSION_TTL = 60 * 60

# Subject integer codes used across IXL APIs
SUBJECT_IDS = {"math": 0, "ela": 1, "science": 2, "social_studies": 3, "spanish": 5}
ALL_SUBJECTS = "0,1,5"  # math, ela, spanish — the common student set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dir() -> None:
    IXL_DIR.mkdir(mode=0o700, exist_ok=True)


def _log(msg: str, verbose: bool = True) -> None:
    """Print to stderr so it doesn't pollute --json stdout."""
    if verbose:
        print(msg, file=sys.stderr)


def _escape_env_value(val: str) -> str:
    """Escape special chars for safe .env storage."""
    val = val.replace("\\", "\\\\")
    val = val.replace('"', '\\"')
    val = val.replace("\n", "\\n")
    return val


def _unescape_env_value(val: str) -> str:
    """Unescape .env value (reverse of _escape_env_value)."""
    result = []
    i = 0
    while i < len(val):
        if val[i] == "\\" and i + 1 < len(val):
            nxt = val[i + 1]
            if nxt == "n":
                result.append("\n")
            elif nxt == "\\":
                result.append("\\")
            elif nxt == '"':
                result.append('"')
            else:
                result.append(nxt)
            i += 2
        else:
            result.append(val[i])
            i += 1
    return "".join(result)


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Handles KEY=VALUE and KEY="VALUE"."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            env[key] = _unescape_env_value(val)
    return env


def load_config() -> dict[str, str]:
    """Load credentials + site config. Priority: env vars > ~/.ixl/.env.

    If IXL_EMAIL contains '@', splits into username and school slug:
      "jdoe@myschool" → username="jdoe", school="myschool"
    """
    cfg: dict[str, str] = {}

    # .env file (lower priority)
    env = _load_env_file(ENV_PATH)
    if env.get("IXL_EMAIL"):
        cfg["email"] = env["IXL_EMAIL"]
    if env.get("IXL_PASSWORD"):
        cfg["password"] = env["IXL_PASSWORD"]
    if env.get("IXL_SCHOOL"):
        cfg["school"] = env["IXL_SCHOOL"]

    # Environment variables (highest priority)
    if os.environ.get("IXL_EMAIL"):
        cfg["email"] = os.environ["IXL_EMAIL"]
    if os.environ.get("IXL_PASSWORD"):
        cfg["password"] = os.environ["IXL_PASSWORD"]
    if os.environ.get("IXL_SCHOOL"):
        cfg["school"] = os.environ["IXL_SCHOOL"]

    if not cfg.get("email") or not cfg.get("password"):
        raise RuntimeError(
            "No credentials found. Set IXL_EMAIL/IXL_PASSWORD env vars, "
            "create ~/.ixl/.env, or run `ixl init`."
        )

    # Parse username@school format
    email = cfg["email"]
    if "@" in email:
        parts = email.split("@", 1)
        cfg["username"] = parts[0]
        # Only use the domain part as school if no explicit IXL_SCHOOL is set
        # and it doesn't look like a real email domain
        domain = parts[1]
        if not cfg.get("school") and "." not in domain:
            cfg["school"] = domain
    else:
        cfg["username"] = email

    cfg.setdefault("school", "")

    return cfg


def _session_path_for(email: str) -> Path:
    """Return per-account session path: ~/.ixl/sessions/{sha256(email)[:12]}.json"""
    sessions_dir = IXL_DIR / "sessions"
    sessions_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    h = hashlib.sha256(email.encode()).hexdigest()[:12]
    return sessions_dir / f"{h}.json"


def save_session(data: dict, *, path: Optional[Path] = None) -> None:
    _ensure_dir()
    target = path or SESSION_PATH
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data["ts"] = time.time()
    # Atomic write: write to temp file, then rename into place.
    # Use os.open to create with 0o600 from the start (no TOCTOU race).
    tmp_path = target.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(str(tmp_path), str(target))


def load_session(*, path: Optional[Path] = None) -> Optional[dict]:
    """Return saved session data if still fresh, else None.

    If *path* doesn't exist but the legacy shared SESSION_PATH does,
    migrate (copy) the old file to *path* so subsequent runs use it.
    """
    target = path or SESSION_PATH

    # Migration: copy legacy shared session to per-account path
    if not target.exists() and target != SESSION_PATH and SESSION_PATH.exists():
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(str(SESSION_PATH), str(target))

    if not target.exists():
        return None
    try:
        with open(target) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - data.get("ts", 0) > SESSION_TTL:
        return None
    return data


# ---------------------------------------------------------------------------
# IXL session management
# ---------------------------------------------------------------------------

class IXLSession:
    """Wraps requests.Session with Playwright login + session caching."""

    def __init__(self, verbose: bool = True):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/html, */*",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.cfg = load_config()
        self.verbose = verbose
        self._logged_in = False
        self._last_request_time = 0.0
        self._cache: dict = {}
        self._session_path = _session_path_for(self.cfg["email"])

    def _sleep_if_needed(self) -> None:
        """Add jitter between requests. IXL is pickier — use 1-3s."""
        now = time.time()
        elapsed = now - self._last_request_time
        target_wait = random.uniform(1.0, 3.0)
        if elapsed < target_wait:
            time.sleep(target_wait - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Wrapper with rate limiting and exponential backoff on 429."""
        max_retries = 3
        base_delay = 3.0
        resp: Optional[requests.Response] = None

        for attempt in range(max_retries):
            self._sleep_if_needed()
            resp = self.s.request(method, url, **kwargs)

            if resp.status_code == 429:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                _log(f"Rate limited (429). Retrying in {delay:.1f}s...", self.verbose)
                time.sleep(delay)
                continue

            return resp

        if resp is None:
            raise RuntimeError("Request failed completely")
        if resp.status_code == 429:
            raise requests.exceptions.HTTPError(
                f"Rate limited (429) after {max_retries} retries", response=resp,
            )
        return resp

    # -- login / session cache --

    def ensure_logged_in(self) -> None:
        if self._logged_in:
            return

        cached = load_session(path=self._session_path)
        if cached:
            cookies = cached.get("cookies", cached)
            domains = cached.get("domains", {})
            for name, value in cookies.items():
                if name in ("ts", "cookies", "domains"):
                    continue
                domain = domains.get(name, ".ixl.com")
                self.s.cookies.set(name, value, domain=domain, path="/")

            try:
                r = self._request(
                    "GET", f"{BASE_URL}/analytics/student-summary-practice",
                    allow_redirects=False, timeout=15,
                )
                if r.status_code == 200:
                    self._logged_in = True
                    _log("Using cached session.", self.verbose)
                    return
            except requests.RequestException:
                pass

        self._do_login()

    def _do_login(self) -> None:
        """Log in to IXL using Playwright.

        Cloudflare blocks direct POST login from requests, so we use a real
        browser via Playwright. After login, cookies are exported to the
        requests.Session for all subsequent API calls.
        """
        # Lazy import — playwright is optional, only needed for login
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is required for IXL login but not installed.\n"
                "Install it with:\n"
                "  pip install 'ixl[browser]'\n"
                "  playwright install chromium\n"
                "\n"
                "Or manually: pip install playwright && playwright install chromium"
            )

        _log("Logging in to IXL via browser...", self.verbose)

        school = self.cfg.get("school", "")
        username = self.cfg.get("username", self.cfg["email"])

        signin_path = f"/signin/{school}" if school else "/signin"
        signin_url = f"{BASE_URL}{signin_path}"

        cookie_dict: dict[str, str] = {}
        cookie_domains: dict[str, str] = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=DEFAULT_UA)
            page = context.new_page()

            try:
                # Navigate to signin page
                page.goto(signin_url, wait_until="networkidle", timeout=30000)

                # Fill login form
                page.wait_for_selector("#siusername", timeout=10000)
                page.fill("#siusername", username)
                page.fill("#sipassword", self.cfg["password"])

                # Click submit
                page.click("#custom-signin-button")

                # Wait for redirect to dashboard (successful login)
                page.wait_for_url("**/dashboard**", timeout=15000)

                _log("Browser login successful.", self.verbose)

                # Visit analytics page to initialize report cookies
                page.goto(f"{BASE_URL}/analytics/score-grid", wait_until="networkidle", timeout=30000)
                time.sleep(2)

                # Export ALL cookies from browser context, preserving domains
                browser_cookies = context.cookies()
                for c in browser_cookies:
                    domain = c.get("domain", "")
                    if "ixl.com" in domain:
                        name = c.get("name", "")
                        value = c.get("value", "")
                        if name:
                            cookie_dict[name] = value
                            cookie_domains[name] = domain

            except Exception as exc:
                # Try to detect error messages on the page
                error_msg = ""
                try:
                    error_el = page.query_selector(".error-message, .signin-error, #signin-error")
                    if error_el:
                        error_msg = error_el.inner_text()
                except Exception:
                    pass

                browser.close()

                detail = f": {error_msg}" if error_msg else ""
                raise RuntimeError(
                    f"Login failed{detail}. Check credentials with `ixl init`.\n"
                    f"Original error: {exc}"
                )

            browser.close()

        if not cookie_dict:
            raise RuntimeError("Login appeared to succeed but no cookies were captured.")

        # Transfer cookies to requests.Session, preserving original domains
        for name, value in cookie_dict.items():
            domain = cookie_domains.get(name, ".ixl.com")
            self.s.cookies.set(name, value, domain=domain, path="/")

        self._logged_in = True
        save_session({"cookies": cookie_dict, "domains": cookie_domains}, path=self._session_path)
        _log("Session cookies saved.", self.verbose)

    # -- data fetching --

    def fetch_json(
        self, path: str, params: Optional[dict] = None,
        method: str = "GET", **kwargs,
    ) -> Union[dict, list, None]:
        """Fetch JSON from an IXL API path."""
        self.ensure_logged_in()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        r = self._request(method, url, params=params, timeout=20, **kwargs)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as exc:
            _log(f"API {path} JSON parse error: {exc}", self.verbose)
            return None

    def fetch_page(self, path: str, params: Optional[dict] = None) -> str:
        """Fetch an HTML page and return the text."""
        self.ensure_logged_in()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        r = self._request("GET", url, params=params, timeout=20)
        r.raise_for_status()
        return r.text

    def fetch_raw(self, path: str, params: Optional[dict] = None) -> requests.Response:
        """Fetch a raw response (for inspecting status codes, headers, etc.)."""
        self.ensure_logged_in()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        return self._request("GET", url, params=params, timeout=20)
