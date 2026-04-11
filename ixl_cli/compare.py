"""
IXL compare — multi-account side-by-side comparison.

Reads ~/.ixl/accounts.env (format: name:email:password, one per line)
and builds a unified comparison dict from per-account summary data.
"""

from ixl_cli.session import ACCOUNTS_PATH


def load_accounts() -> list[dict]:
    """Load student accounts from ~/.ixl/accounts.env.

    Format: one account per line as `name:email:password`.
    Lines starting with # are comments. Blank lines are ignored.
    Returns an empty list if the file does not exist.
    """
    if not ACCOUNTS_PATH.exists():
        return []

    accounts = []
    with open(ACCOUNTS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            name, email, password = parts
            accounts.append({"name": name, "email": email, "password": password})
    return accounts


def _count_skills(skills_data: list) -> dict:
    """Count mastered (90+), excellent (80-89), and total skills across subjects."""
    mastered = 0
    excellent = 0
    total = 0
    for subj in skills_data:
        for sk in subj.get("skills", []):
            score = sk.get("smart_score", 0) or 0
            total += 1
            if score >= 90:
                mastered += 1
            elif score >= 80:
                excellent += 1
    return {"mastered": mastered, "excellent": excellent, "total": total}


def build_comparison(summaries: list[dict]) -> dict:
    """Build a comparison dict from per-account summary data.

    Args:
        summaries: List of dicts, each with keys: student, skills, trouble_spots, usage.

    Returns:
        {"children": [{name, grade, skills_summary, trouble_spot_count, usage}, ...]}
    """
    children = []
    for s in summaries:
        student = s.get("student") or {}
        skills_summary = _count_skills(s.get("skills", []))
        usage_raw = s.get("usage") or {}
        children.append({
            "name": student.get("name", "Unknown"),
            "grade": student.get("grade", ""),
            "skills_summary": skills_summary,
            "trouble_spot_count": len(s.get("trouble_spots", [])),
            "usage": {
                "time_spent_min": usage_raw.get("time_spent_min", 0),
                "questions_answered": usage_raw.get("questions_answered", 0),
                "days_active": usage_raw.get("days_active", 0),
            },
        })
    return {"children": children}
