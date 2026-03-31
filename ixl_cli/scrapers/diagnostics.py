"""
IXL Real-Time Diagnostic scraper.

Uses GET /analytics/student-summary-diagnostic to fetch diagnostic
growth data per subject. Handles the case where a student has no
diagnostic data (empty data arrays).
"""

from typing import Optional

import requests

from ixl_cli.session import IXLSession, SUBJECT_IDS, _log

# Map subjectInt → human-readable name
_SUBJECT_NAMES = {v: k.replace("_", " ").title() for k, v in SUBJECT_IDS.items()}


def scrape_diagnostics(session: IXLSession, child: Optional[dict] = None) -> list[dict]:
    """Scrape diagnostic levels per subject.

    Args:
        session: Authenticated IXL session.
        child: Ignored for student accounts (kept for CLI compatibility).

    Returns list of dicts per subject:
    [
        {
            "subject": "Math",
            "overall_level": "2nd grade",
            "max_score": 1400,
            "strands": [],
            "last_assessed": "",
            "scores": [{"date": "...", "score": 450}, ...]
        }
    ]
    """
    session.ensure_logged_in()

    try:
        data = session.fetch_json("/analytics/student-summary-diagnostic")
    except requests.exceptions.HTTPError as exc:
        _log(f"Warning: Diagnostics API error: {exc}", session.verbose)
        return []
    if not isinstance(data, dict):
        _log("Warning: No diagnostic data returned.", session.verbose)
        return []

    diagnostics: list[dict] = []

    growth = data.get("diagnosticGrowthOverTime", {})
    grade_level = growth.get("gradeLevel", {})
    grade_label = grade_level.get("abbreviatedPageTitle", "")

    growth_data = growth.get("diagnosticGrowthData", [])
    if not growth_data:
        _log("No diagnostic growth data found (student may not have taken diagnostics).", session.verbose)
        return []

    for entry in growth_data:
        if not isinstance(entry, dict):
            continue

        raw_subj = entry.get("subjectInt")
        subject_int: int = int(raw_subj) if raw_subj is not None else -1
        subject_name = _SUBJECT_NAMES.get(subject_int, f"Subject {subject_int}")
        max_score = entry.get("maxPossibleScore", 0)
        raw_data = entry.get("data", [])

        # Parse score history
        scores: list[dict] = []
        last_assessed = ""
        latest_score = ""
        for point in raw_data:
            if not isinstance(point, dict):
                continue
            score_entry = {
                "date": point.get("date", point.get("dateStr", "")),
                "score": point.get("score", point.get("diagnosticScore", 0)),
                "level": point.get("gradeEquivalent", point.get("level", "")),
            }
            scores.append(score_entry)
            if score_entry["date"]:
                last_assessed = score_entry["date"]
            if score_entry["level"]:
                latest_score = str(score_entry["level"])

        overall = latest_score or grade_label or ""

        diagnostics.append({
            "subject": subject_name,
            "overall_level": overall,
            "max_score": max_score,
            "strands": [],  # Diagnostic summary doesn't include strand-level data
            "last_assessed": last_assessed,
            "scores": scores,
            "has_data": len(scores) > 0,
        })

    if not diagnostics:
        _log("No diagnostic data found (student may not have taken diagnostics).", session.verbose)

    return diagnostics
