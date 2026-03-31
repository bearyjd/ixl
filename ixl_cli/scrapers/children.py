"""
Student profile for IXL student accounts.

These are STUDENT accounts (not parent accounts), so there is no
multi-child discovery. This module returns the logged-in student's
own info as a single-item list for CLI compatibility.

Student name is extracted from the trouble-spots API response
(firstName / lastName fields).
"""

from typing import Optional

import requests

from ixl_cli.session import ALL_SUBJECTS, IXLSession, _log


def scrape_children(session: IXLSession) -> list[dict]:
    """Return a single-item list with the logged-in student's info.

    Fetches the student's name from the trouble-spots endpoint which
    includes firstName/lastName in its response.
    """
    session.ensure_logged_in()

    name = ""
    grade = ""

    # The trouble-spots/run endpoint returns firstName and lastName
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=30)
    try:
        data = session.fetch_json(
            "/analytics/trouble-spots/run",
            params={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "subjects": ALL_SUBJECTS,
                "lowGrade": "-2",
                "highGrade": "12",
            },
            method="POST",
        )
    except requests.exceptions.HTTPError:
        data = None

    if isinstance(data, dict):
        first = data.get("firstName", "")
        last = data.get("lastName", "")
        if first or last:
            name = f"{first} {last}".strip()

    # Fallback: use the username from config
    if not name:
        name = session.cfg.get("username", session.cfg.get("email", "Student"))

    # Try to get grade from score-grid-defaults
    school_year_start = date(end.year, 8, 1) if end.month >= 8 else date(end.year - 1, 8, 1)
    try:
        defaults = session.fetch_json(
            "/analytics/score-grid-defaults",
            params={
                "startDate": school_year_start.isoformat(),
                "endDate": end.isoformat(),
                "subjects": ALL_SUBJECTS,
                "student": "",
            },
        )
    except requests.exceptions.HTTPError:
        defaults = None
    if isinstance(defaults, dict):
        grade_num = defaults.get("grade")
        if grade_num is not None:
            grade = str(grade_num)

    student = {
        "name": name,
        "uid": "self",
        "grade": grade,
    }

    return [student]


def resolve_child(children: list[dict], name_hint: Optional[str]) -> Optional[dict]:
    """Resolve a child by name. For student accounts, always returns the student.

    Kept for CLI compatibility — the --child flag is a no-op for student accounts.
    """
    if not children:
        return None
    if name_hint is None:
        return children[0]

    hint = name_hint.lower()

    # Exact first-name match
    for c in children:
        first = c["name"].split()[0].lower() if c["name"] else ""
        if hint == first:
            return c

    # Substring match
    for c in children:
        if hint in c["name"].lower():
            return c

    # For student accounts, just return the only entry
    return children[0]
