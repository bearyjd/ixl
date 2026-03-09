"""
IXL skill progress scraper.

Uses two endpoints:
1. GET /analytics/student-summary-practice — overall summary stats + mastered/proficient lists
2. GET /analytics/score-chart/run?subject={0|1|5}&highscore=true&... — detailed per-skill scores

SmartScores: 0-100, 80+ = proficient, 90+ = mastered (per IXL's system).
"""

from datetime import date, timedelta
from typing import Optional, Union

from ixl_cli.session import ALL_SUBJECTS, IXLSession, SUBJECT_IDS, _log

# Map subjectInt → display name
_SUBJECT_DISPLAY = {0: "Math", 1: "ELA", 2: "Science", 3: "Social Studies", 5: "Spanish"}


def _discover_active_grades(
    session: IXLSession,
    subject_int: int,
    default_grade: int,
    start_str: str,
    end_str: str,
) -> list[int]:
    """Scan grades for assigned/practiced skills. Caches per session.

    Checks default grade ± 4 levels (covers remedial and advanced work).
    """
    cache_key = f"_active_grades_{subject_int}"
    cached = getattr(session, cache_key, None)
    if cached is not None:
        return cached

    low = max(-2, default_grade - 4)
    high = min(12, default_grade + 4)
    active: list[int] = []

    for grade_num in range(low, high + 1):
        data = _fetch_score_chart(session, subject_int, grade_num, start_str, end_str)
        if not isinstance(data, dict):
            continue

        table = data.get("gradesModeData", {}).get("table", [])
        if _has_activity(table):
            active.append(grade_num)

    if not active:
        active = [default_grade]

    setattr(session, cache_key, active)
    return active


def _has_activity(table: list) -> bool:
    for block in table:
        for cat in block.get("categories", []):
            for sk in cat.get("skills", []):
                if sk.get("isSkillSuggested") or (sk.get("questionsAnswered", 0) or 0) > 0:
                    return True
    return False


def _fetch_score_chart(
    session: IXLSession, subject_int: int, grade_num: int,
    start_str: str, end_str: str,
) -> Union[dict, list, None]:
    return session.fetch_json(
        "/analytics/score-chart/run",
        params={
            "subject": str(subject_int),
            "standardDoc": "",
            "highscore": "true",
            "scoresHighlighted": "none",
            "scoresDisplayed": "all",
            "scoringType": "best_attempt",
            "goalOfProficient": "true",
            "grades": str(grade_num),
            "timePeriod": "5",
            "startDate": start_str,
            "endDate": end_str,
            "subjects": ALL_SUBJECTS,
            "rosterClass": "",
            "courseId": "",
            "skillSource": "1",
        },
    )


def scrape_skills(
    session: IXLSession,
    child: Optional[dict] = None,
    subject: Optional[str] = None,
) -> list[dict]:
    """Scrape skill progress / SmartScores.

    Args:
        session: Authenticated IXL session.
        child: Ignored for student accounts (kept for CLI compat).
        subject: Filter by subject ("math", "ela", "spanish"). None = all.

    Returns list of dicts per subject:
    [
        {
            "subject": "Math",
            "grade": "2",
            "skills": [
                {
                    "id": "LHN",
                    "name": "Hundred chart",
                    "smart_score": 100,
                    "time_spent_min": 5.75,
                    "questions": 24,
                    "last_practiced": "2025-10-15",
                    "skill_code": "A.1"
                }
            ]
        }
    ]
    """
    session.ensure_logged_in()

    # Determine which subjects to fetch
    if subject:
        subject_key = subject.lower().replace(" ", "_")
        if subject_key in SUBJECT_IDS:
            subject_ints = [SUBJECT_IDS[subject_key]]
        else:
            _log(f"Unknown subject '{subject}', fetching all.", session.verbose)
            subject_ints = [0, 1, 5]
    else:
        subject_ints = [0, 1, 5]

    end = date.today()
    start_str = "2025-08-01"
    defaults = session.fetch_json(
        "/analytics/score-grid-defaults",
        params={
            "startDate": start_str,
            "endDate": end.isoformat(),
            "subjects": ALL_SUBJECTS,
            "student": "",
        },
    )
    default_grade = 2
    if isinstance(defaults, dict):
        g = defaults.get("grade")
        if g is not None:
            default_grade = int(g)

    skills_data: list[dict] = []

    for subj_int in subject_ints:
        subj_name = _SUBJECT_DISPLAY.get(subj_int, f"Subject {subj_int}")

        end_str = end.isoformat()
        grades_to_fetch = _discover_active_grades(
            session, subj_int, default_grade, start_str, end_str,
        )

        for grade_num in grades_to_fetch:
            data = _fetch_score_chart(session, subj_int, grade_num, start_str, end_str)

            if not isinstance(data, dict):
                continue

            grades_data = data.get("gradesModeData", {})
            table = grades_data.get("table", [])
            graph = grades_data.get("graph", {})
            mastered_count = graph.get("mastered", {}).get("numSkills", 0) if graph else 0
            excellent_count = graph.get("excellent", {}).get("numSkills", 0) if graph else 0

            skills: list[dict] = []

            for grade_block in table:
                if not isinstance(grade_block, dict):
                    continue
                for cat in grade_block.get("categories", []):
                    if not isinstance(cat, dict):
                        continue
                    cat_name = cat.get("categoryName", "")
                    cat_code = cat.get("categoryCode", "")

                    for sk in cat.get("skills", []):
                        if not isinstance(sk, dict):
                            continue

                        permacode = sk.get("permacode", "")
                        skill_num = sk.get("lightweightSkillNumber", "")
                        skill_code = f"{cat_code}.{skill_num}" if cat_code and skill_num else permacode

                        seconds = sk.get("secondsSpent", 0) or 0
                        time_min = round(seconds / 60, 2) if seconds else 0

                        skills.append({
                            "id": permacode,
                            "name": sk.get("skillName", ""),
                            "smart_score": sk.get("score", 0) or 0,
                            "time_spent_min": time_min,
                            "questions": sk.get("questionsAnswered", 0) or 0,
                            "last_practiced": sk.get("lastPracticedLocalDateStr", ""),
                            "skill_code": skill_code,
                            "category": cat_name,
                            "suggested": bool(sk.get("isSkillSuggested")),
                        })

            if skills:
                grade_label = f"Grade {grade_num}" if len(grades_to_fetch) > 1 else str(grade_num)
                skills_data.append({
                    "subject": f"{subj_name} ({grade_label})" if len(grades_to_fetch) > 1 else subj_name,
                    "grade": str(grade_num),
                    "mastered": mastered_count,
                    "excellent": excellent_count,
                    "skills": skills,
                })

    if not skills_data:
        _log("Warning: No skill data found.", session.verbose)

    return skills_data
