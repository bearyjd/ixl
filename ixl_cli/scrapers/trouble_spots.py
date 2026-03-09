"""
IXL trouble spots scraper.

Uses two endpoints:
1. GET /analytics/student-summary-practice-next — top trouble spots (quick)
2. POST /analytics/trouble-spots/run — detailed trouble spots with scores

The detailed endpoint returns skill-level data including incorrect answer
counts, scores, and grade/skill codes.
"""

from datetime import date, timedelta
from typing import Optional

from ixl_cli.session import ALL_SUBJECTS, IXLSession, _log


def scrape_trouble_spots(
    session: IXLSession,
    child: Optional[dict] = None,
) -> list[dict]:
    """Scrape trouble spots for the logged-in student.

    Args:
        session: Authenticated IXL session.
        child: Ignored for student accounts (kept for CLI compat).

    Returns list of dicts:
    [
        {
            "skill": "F62",
            "name": "Do you have enough money? - up to $1",
            "subject": "Math",
            "skill_code": "AA.11",
            "grade": "2nd",
            "missed_count": 22,
            "score": 93,
            "last_attempted": ""
        }
    ]
    """
    session.ensure_logged_in()
    trouble_spots: list[dict] = []

    # Use the detailed trouble-spots endpoint
    end = date.today()
    start = end - timedelta(days=30)

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

    if isinstance(data, dict):
        status = data.get("status", "")
        if status == "NO_TROUBLE_SPOTS":
            _log("No trouble spots found — great job!", session.verbose)
            return []

        table = data.get("table", [])
        for item in table:
            if not isinstance(item, dict):
                continue

            # Extract score from the students array (first entry is this student)
            score = 0
            students = item.get("students", [])
            if students and isinstance(students[0], dict):
                score = students[0].get("score", 0) or 0

            trouble_spots.append({
                "skill": item.get("permacode", ""),
                "name": item.get("skillName", ""),
                "subject": _guess_subject(item),
                "skill_code": item.get("skillCode", ""),
                "grade": item.get("gradeShortOrdinal", ""),
                "missed_count": item.get("numberOfIncorrectAnswers", 0) or 0,
                "score": score,
                "last_attempted": "",
            })

    # Fallback: try the quick summary endpoint
    if not trouble_spots:
        summary = session.fetch_json("/analytics/student-summary-practice-next")
        if isinstance(summary, dict):
            ts_data = summary.get("troubleSpots", {})
            top_spots = ts_data.get("topTroubleSpots", [])
            for spot in top_spots:
                if not isinstance(spot, dict):
                    continue
                trouble_spots.append({
                    "skill": spot.get("permacode", ""),
                    "name": spot.get("skillName", ""),
                    "subject": spot.get("subjectName", ""),
                    "skill_code": "",
                    "grade": "",
                    "missed_count": spot.get("numQuestionsMissed", 0) or 0,
                    "score": 0,
                    "last_attempted": "",
                })

    if not trouble_spots:
        _log("Warning: No trouble spot data found.", session.verbose)

    return trouble_spots


def _guess_subject(item: dict) -> str:
    """Guess subject from available fields in a trouble spot item."""
    # The detailed endpoint doesn't always include subject name directly,
    # but skill codes can hint at it. For now, return empty if not available.
    return item.get("subjectName", "") or item.get("subject", "")
