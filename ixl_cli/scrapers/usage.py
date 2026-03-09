"""
IXL usage stats scraper.

Uses two endpoints:
1. GET /analytics/student-usage/run — detailed session-by-session usage
2. GET /analytics/student-summary-practice — overall summary stats

The student-usage endpoint returns per-session breakdowns including
skills practiced, time spent, and score changes within each session.
"""

from datetime import date, timedelta
from typing import Optional

from ixl_cli.session import ALL_SUBJECTS, IXLSession, _log


def scrape_usage(
    session: IXLSession,
    child: Optional[dict] = None,
    days: int = 7,
) -> dict:
    """Scrape usage stats for the logged-in student.

    Args:
        session: Authenticated IXL session.
        child: Ignored for student accounts (kept for CLI compat).
        days: Number of days to look back (default 7).

    Returns dict:
    {
        "period": "last_7_days",
        "time_spent_min": 45,
        "questions_answered": 187,
        "skills_practiced": 12,
        "days_active": 4,
        "sessions": [...],
        "top_categories": [...]
    }
    """
    session.ensure_logged_in()

    end = date.today()
    start = end - timedelta(days=days)

    data = session.fetch_json(
        "/analytics/student-usage/run",
        params={
            "rosterClass": "",
            "courseId": "",
            "subjects": ALL_SUBJECTS,
            "lowGrade": "-2",
            "highGrade": "12",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        },
    )

    if not isinstance(data, dict):
        _log("Warning: No usage data returned.", session.verbose)
        return _empty_usage(days)

    # Parse summary
    summary = data.get("summary", {})
    time_seconds = summary.get("practiceTimeSpent", 0) or 0
    time_min = round(time_seconds / 60, 1)
    questions = summary.get("questionsAnswered", 0) or 0
    skills_count = summary.get("numSkills", 0) or 0

    # Parse sessions for days_active count
    sessions_raw = data.get("table", [])
    sessions: list[dict] = []
    active_dates: set[str] = set()

    for entry in sessions_raw:
        if not isinstance(entry, dict):
            continue

        session_date = entry.get("sessionStartLocalDateStr", "")
        if session_date:
            active_dates.add(session_date)

        session_seconds = entry.get("secondsSpent", 0) or 0

        # Parse skills within session
        session_skills: list[dict] = []
        for sk in entry.get("skills", []):
            if not isinstance(sk, dict):
                continue
            sk_seconds = sk.get("secondsSpent", 0) or 0
            session_skills.append({
                "name": sk.get("skillName", ""),
                "permacode": sk.get("permacode", ""),
                "questions": sk.get("questionsAnswered", 0) or 0,
                "time_min": round(sk_seconds / 60, 1),
                "score_before": sk.get("earlierScore", 0) or 0,
                "score_after": sk.get("score", 0) or 0,
                "correct": sk.get("correctAnswers", 0) or 0,
            })

        sessions.append({
            "date": session_date,
            "date_range": entry.get("dateTimeRange", ""),
            "time_min": round(session_seconds / 60, 1),
            "questions": entry.get("questionsAnswered", 0) or 0,
            "num_skills": entry.get("numSkills", 0) or 0,
            "skills": session_skills,
        })

    # Parse top categories
    categories_raw = data.get("categories", [])
    top_categories: list[dict] = []
    for cat in categories_raw:
        if not isinstance(cat, dict):
            continue
        top_categories.append({
            "grade": cat.get("fullGradeName", ""),
            "category": cat.get("categoryName", ""),
            "questions": cat.get("questionsAnswered", 0) or 0,
        })

    return {
        "period": f"last_{days}_days",
        "time_spent_min": time_min,
        "questions_answered": questions,
        "skills_practiced": skills_count,
        "days_active": len(active_dates),
        "sessions": sessions,
        "top_categories": top_categories,
    }


def _empty_usage(days: int) -> dict:
    """Return an empty usage dict with the correct period."""
    return {
        "period": f"last_{days}_days",
        "time_spent_min": 0,
        "questions_answered": 0,
        "skills_practiced": 0,
        "days_active": 0,
        "sessions": [],
        "top_categories": [],
    }
