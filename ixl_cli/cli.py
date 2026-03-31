"""
ixl — IXL student account CLI scraper.

Logs in via Playwright (Cloudflare-resistant), caches session cookies,
and fetches data from IXL's JSON analytics APIs.

Usage:
    ixl init                                    — set up credentials interactively
    ixl children                                — show student profile info
    ixl diagnostics [--child NAME] [--json]     — diagnostic levels per subject
    ixl skills      [--child NAME] [--subject SUBJ] [--json]  — skill scores
    ixl trouble     [--child NAME] [--json]     — trouble spots
    ixl usage       [--child NAME] [--days N] [--json]         — usage stats
    ixl summary     [--child NAME] [--json]     — everything in one shot
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime

import requests

from ixl_cli.session import (
    ENV_PATH,
    GOALS_PATH,
    IXL_DIR,
    IXLSession,
    _ensure_dir,
    _escape_env_value,
    _log,
)
from ixl_cli.goals import evaluate_goals, generate_defaults, load_goals, save_goals
from ixl_cli.scrapers.children import resolve_child, scrape_children
from ixl_cli.scrapers.diagnostics import scrape_diagnostics
from ixl_cli.scrapers.skills import scrape_skills
from ixl_cli.scrapers.trouble_spots import scrape_trouble_spots
from ixl_cli.scrapers.usage import scrape_usage


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def output_children(children: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(children, indent=2))
        return
    if not children:
        print("No student info found.")
        return
    print(f"\n{'Name':<25} {'UID':<15} {'Grade'}")
    print("-" * 50)
    for c in children:
        print(f"{c['name']:<25} {c['uid']:<15} {c.get('grade', '')}")
    print()


def output_diagnostics(diagnostics: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(diagnostics, indent=2))
        return
    if not diagnostics:
        print("No diagnostic data found (student may not have taken diagnostics).")
        return
    for diag in diagnostics:
        subject = diag.get("subject", "Unknown")
        overall = diag.get("overall_level", "—")
        last = diag.get("last_assessed", "")
        has_data = diag.get("has_data", False)
        max_score = diag.get("max_score", 0)
        print(f"\n  {subject} — Level: {overall}")
        if max_score:
            print(f"  Max possible score: {max_score}")
        if last:
            print(f"  Last assessed: {last}")
        if not has_data:
            print("  (No diagnostic assessments completed yet)")
        scores = diag.get("scores", [])
        if scores:
            print(f"\n  {'Date':<15} {'Score':<10} {'Level'}")
            print(f"  {'-' * 40}")
            for s in scores:
                print(f"  {s.get('date', ''):<15} {str(s.get('score', '')):<10} {s.get('level', '')}")
    print()


def output_skills(skills_data: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(skills_data, indent=2))
        return
    if not skills_data:
        print("No skill data found.")
        return
    for subj in skills_data:
        subject = subj.get("subject", "Unknown")
        grade = subj.get("grade", "")
        mastered = subj.get("mastered", 0)
        excellent = subj.get("excellent", 0)
        header = f"  {subject}"
        if grade:
            header += f" (Grade {grade})"
        print(f"\n{header}")
        if mastered or excellent:
            print(f"  Mastered: {mastered}  |  Excellent: {excellent}")
        skills = subj.get("skills", [])
        if not skills:
            print("  No skills recorded.")
            continue
        print(f"\n  {'Code':<8} {'Skill':<40} {'Score':<8} {'Time':<8} {'Qs'}")
        print(f"  {'-' * 70}")
        for sk in skills:
            code = sk.get("skill_code", sk.get("id", ""))[:7]
            name = sk.get("name", "")[:39]
            score = str(sk.get("smart_score", ""))[:7]
            time_m = str(sk.get("time_spent_min", ""))[:7]
            qs = str(sk.get("questions", ""))
            print(f"  {code:<8} {name:<40} {score:<8} {time_m:<8} {qs}")
    print()


def output_trouble_spots(trouble_spots: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(trouble_spots, indent=2))
        return
    if not trouble_spots:
        print("No trouble spots found — great job!")
        return
    print(f"\n  {'Code':<8} {'Name':<40} {'Grade':<8} {'Missed':<8} {'Score'}")
    print(f"  {'-' * 75}")
    for ts in trouble_spots:
        code = ts.get("skill_code", ts.get("skill", ""))[:7]
        name = ts.get("name", "")[:39]
        grade = ts.get("grade", "")[:7]
        missed = str(ts.get("missed_count", ""))[:7]
        score = str(ts.get("score", ""))
        print(f"  {code:<8} {name:<40} {grade:<8} {missed:<8} {score}")
    print()


def output_usage(usage: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(usage, indent=2))
        return
    if not usage:
        print("No usage data found.")
        return
    period = usage.get("period", "unknown")
    print(f"\n  Usage ({period}):")
    print(f"    Time spent:         {usage.get('time_spent_min', 0)} minutes")
    print(f"    Questions answered: {usage.get('questions_answered', 0)}")
    print(f"    Skills practiced:   {usage.get('skills_practiced', 0)}")
    print(f"    Days active:        {usage.get('days_active', 0)}")

    # Top categories
    categories = usage.get("top_categories", [])
    if categories:
        print(f"\n    Top categories:")
        for cat in categories[:5]:
            print(f"      {cat.get('category', '')}: {cat.get('questions', 0)} questions")

    # Session details
    sessions = usage.get("sessions", [])
    if sessions:
        print(f"\n    Recent sessions ({len(sessions)}):")
        for sess in sessions[:5]:
            print(f"      {sess.get('date_range', sess.get('date', ''))}: "
                  f"{sess.get('time_min', 0)} min, "
                  f"{sess.get('questions', 0)} questions, "
                  f"{sess.get('num_skills', 0)} skills")
    print()


def output_assigned(skills_data: list[dict], as_json: bool) -> None:
    all_remaining: list[dict] = []
    totals: dict[str, dict] = {}

    for subj in skills_data:
        subject = subj.get("subject", "Unknown")
        assigned = [sk for sk in subj.get("skills", []) if sk.get("suggested")]
        done = [sk for sk in assigned if sk.get("smart_score", 0) >= 80]
        not_started = [sk for sk in assigned if sk.get("questions", 0) == 0]
        in_progress = [sk for sk in assigned
                       if sk.get("questions", 0) > 0 and sk.get("smart_score", 0) < 80]

        totals[subject] = {
            "assigned": len(assigned),
            "done": len(done),
            "in_progress": len(in_progress),
            "not_started": len(not_started),
            "remaining": len(not_started) + len(in_progress),
        }

        for sk in not_started + in_progress:
            all_remaining.append({**sk, "subject": subject})

    if as_json:
        active_totals = {k: v for k, v in totals.items() if v["assigned"] > 0}
        print(json.dumps({
            "totals": active_totals,
            "remaining": all_remaining,
        }, indent=2))
        return

    grand_assigned = sum(t["assigned"] for t in totals.values())
    grand_done = sum(t["done"] for t in totals.values())
    grand_remaining = sum(t["remaining"] for t in totals.values())

    print(f"\n  Assigned Skills: {grand_done}/{grand_assigned} complete "
          f"({grand_remaining} remaining)")
    print()
    for subject, t in totals.items():
        if t["assigned"] == 0:
            continue
        bar_done = "█" * t["done"]
        bar_prog = "▓" * t["in_progress"]
        bar_todo = "░" * min(t["not_started"], 40)
        print(f"  {subject:<20} {t['done']:>3}/{t['assigned']:<3}  "
              f"{bar_done}{bar_prog}{bar_todo}")
        if t["in_progress"]:
            print(f"    In progress: {t['in_progress']}")
        if t["not_started"]:
            print(f"    Not started: {t['not_started']}")

    if all_remaining:
        print(f"\n  {'Code':<8} {'Subject':<18} {'Skill':<35} {'Score':<8} {'Qs'}")
        print(f"  {'-' * 75}")
        for sk in all_remaining:
            code = sk.get("skill_code", sk.get("id", ""))[:7]
            subj_short = sk.get("subject", "")[:17]
            name = sk.get("name", "")[:34]
            score = str(sk.get("smart_score", 0))[:7]
            qs = str(sk.get("questions", 0))
            print(f"  {code:<8} {subj_short:<18} {name:<35} {score:<8} {qs}")
    print()


def output_goals(goal_status: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(goal_status, indent=2))
        return
    if not goal_status:
        print("No goal data available.")
        return

    week_start = goal_status.get("week_start", "")
    day = goal_status.get("day_of_week", 0)

    from datetime import timedelta as td
    try:
        ws = datetime.fromisoformat(week_start)
        we = ws + td(days=6)
        header = f"  Weekly Goals ({ws.strftime('%a %b %d')} - {we.strftime('%a %b %d')})"
    except (ValueError, TypeError):
        header = "  Weekly Goals"

    print(f"\n{header}")
    print(f"  Day {day} of 7\n")

    labels = {
        "time_min": "Time spent",
        "questions": "Questions",
        "skills_mastered": "Skills mastered",
        "days_active": "Days active",
        "trouble_spots_reduced": "Trouble spots",
    }
    units = {
        "time_min": "min",
        "trouble_spots_reduced": "reduced",
    }

    metrics = goal_status.get("metrics", {})
    for key, label in labels.items():
        m = metrics.get(key)
        if not m:
            continue
        target = m["target"]
        actual = m["actual"]
        status = m["status"]
        pct = m["pct"]
        unit = units.get(key, "")
        suffix = f" {unit}" if unit else ""

        filled = min(10, int(pct / 10))
        bar = "=" * filled + "-" * (10 - filled)

        print(f"    {label:<18} {actual:>4} / {target:<4}{suffix:<8} [{bar}]  {status}")

    print()


def output_summary(
    child: dict | None,
    children: list[dict],
    diagnostics: list[dict],
    skills_data: list[dict],
    trouble_spots: list[dict],
    usage: dict,
    as_json: bool,
    goal_status: dict | None = None,
) -> None:
    if as_json:
        data = {
            "student": child,
            "timestamp": datetime.now().isoformat(),
            "diagnostics": diagnostics,
            "skills": skills_data,
            "trouble_spots": trouble_spots,
            "usage": usage,
        }
        if goal_status is not None:
            data["goals"] = goal_status
        print(json.dumps(data, indent=2))
        return

    name = child["name"] if child else "Student"
    print(f"\n{'=' * 60}")
    print(f"  IXL Summary for: {name}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    print("\n--- Diagnostics ---")
    output_diagnostics(diagnostics, False)

    print("\n--- Skills ---")
    output_skills(skills_data, False)

    print("\n--- Trouble Spots ---")
    output_trouble_spots(trouble_spots, False)

    print("\n--- Usage ---")
    output_usage(usage, False)

    if goal_status is not None:
        print("\n--- Goals ---")
        output_goals(goal_status, False)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    """Interactive setup of credentials."""
    _ensure_dir()
    print("IXL CLI Setup")
    print("=" * 40)
    print("For school accounts, enter username@school (e.g., jdoe@myschool)")
    email = input("IXL Username (or username@school): ").strip()
    password = getpass.getpass("IXL Password: ").strip()
    school = input("School slug (optional, press Enter to skip): ").strip()

    if not email or not password:
        print("Username and password are required.", file=sys.stderr)
        sys.exit(1)

    # Use os.open to create with 0o600 from the start (no TOCTOU race)
    fd = os.open(str(ENV_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f'IXL_EMAIL="{_escape_env_value(email)}"\n')
        f.write(f'IXL_PASSWORD="{_escape_env_value(password)}"\n')
        if school:
            f.write(f'IXL_SCHOOL="{_escape_env_value(school)}"\n')

    print(f"\nCredentials saved to {ENV_PATH}")
    print("Run `ixl children` to verify login works.")


def cmd_children(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    children = scrape_children(session)
    output_children(children, args.json)


def cmd_diagnostics(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    diagnostics = scrape_diagnostics(session)
    output_diagnostics(diagnostics, args.json)


def cmd_skills(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    skills_data = scrape_skills(session, subject=args.subject)
    output_skills(skills_data, args.json)


def cmd_trouble(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    trouble_spots = scrape_trouble_spots(session)
    output_trouble_spots(trouble_spots, args.json)


def cmd_usage(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    usage = scrape_usage(session, days=args.days)
    output_usage(usage, args.json)


def cmd_assigned(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    skills_data = scrape_skills(session, subject=args.subject)
    output_assigned(skills_data, args.json)


def cmd_goals(args: argparse.Namespace) -> None:
    if args.init:
        session = IXLSession(verbose=True)
        _log("Generating goal defaults from last 14 days of usage...", True)

        usage = scrape_usage(session, days=14)
        skills_data = scrape_skills(session)
        defaults = generate_defaults(usage, skills_data)
        save_goals(defaults)

        print(f"\nGoals saved to {GOALS_PATH}")
        print(json.dumps(defaults, indent=2))
        print(f"\nEdit {GOALS_PATH} to adjust targets.")
        return

    goals = load_goals()
    if goals is None:
        print("No goals configured. Run `ixl goals --init`.")
        return

    session = IXLSession(verbose=not args.json)

    # Fetch current week's data (days since Monday)
    today = datetime.now()
    days_since_monday = today.weekday()  # 0=Mon
    usage = scrape_usage(session, days=days_since_monday + 1)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)

    goal_status = evaluate_goals(goals, usage, skills_data, trouble_spots)
    output_goals(goal_status, args.json)


def cmd_summary(args: argparse.Namespace) -> None:
    session = IXLSession(verbose=not args.json)
    children = scrape_children(session)
    child = children[0] if children else None

    diagnostics = scrape_diagnostics(session)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)
    usage = scrape_usage(session)

    # Goals (optional — only included if configured)
    goals = load_goals()
    goal_status = None
    if goals is not None:
        days_since_monday = datetime.now().weekday()
        week_usage = scrape_usage(session, days=days_since_monday + 1)
        goal_status = evaluate_goals(goals, week_usage, skills_data, trouble_spots)

    output_summary(child, children, diagnostics, skills_data, trouble_spots, usage, args.json, goal_status=goal_status)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ixl",
        description="IXL student account CLI scraper",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ixl init
    sp_init = subparsers.add_parser("init", help="Set up credentials")
    sp_init.set_defaults(func=cmd_init)

    # ixl children
    sp_children = subparsers.add_parser("children", help="Show student profile")
    sp_children.add_argument("--json", action="store_true", help="JSON output")
    sp_children.set_defaults(func=cmd_children)

    # ixl diagnostics
    sp_diag = subparsers.add_parser("diagnostics", help="Diagnostic levels per subject")
    sp_diag.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_diag.add_argument("--json", action="store_true", help="JSON output")
    sp_diag.set_defaults(func=cmd_diagnostics)

    # ixl skills
    sp_skills = subparsers.add_parser("skills", help="Skill progress / SmartScores")
    sp_skills.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_skills.add_argument("--subject", type=str, help="Filter by subject (math, ela, spanish)")
    sp_skills.add_argument("--json", action="store_true", help="JSON output")
    sp_skills.set_defaults(func=cmd_skills)

    # ixl trouble
    sp_trouble = subparsers.add_parser("trouble", help="Trouble spots report")
    sp_trouble.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_trouble.add_argument("--json", action="store_true", help="JSON output")
    sp_trouble.set_defaults(func=cmd_trouble)

    # ixl usage
    sp_usage = subparsers.add_parser("usage", help="Usage stats (time, questions, etc.)")
    sp_usage.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_usage.add_argument("--days", type=int, default=7, help="Days to look back (default 7)")
    sp_usage.add_argument("--json", action="store_true", help="JSON output")
    sp_usage.set_defaults(func=cmd_usage)

    # ixl assigned
    sp_assigned = subparsers.add_parser("assigned", help="Teacher-assigned skills remaining")
    sp_assigned.add_argument("--subject", type=str, help="Filter by subject (math, ela, spanish)")
    sp_assigned.add_argument("--json", action="store_true", help="JSON output")
    sp_assigned.set_defaults(func=cmd_assigned)

    # ixl summary
    sp_sum = subparsers.add_parser("summary", help="Full summary (all data)")
    sp_sum.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_sum.add_argument("--json", action="store_true", help="JSON output")
    sp_sum.set_defaults(func=cmd_summary)

    # ixl goals
    sp_goals = subparsers.add_parser("goals", help="Weekly goal tracking")
    sp_goals.add_argument("--init", action="store_true", help="Generate goals from recent usage")
    sp_goals.add_argument("--json", action="store_true", help="JSON output")
    sp_goals.set_defaults(func=cmd_goals)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
