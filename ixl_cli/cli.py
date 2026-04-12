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
    ixl summary     [--child NAME] [--no-save] [--json]        — everything in one shot
    ixl trends      [--days N] [--json]         — historical progress trends
    ixl goals       [--init] [--json]           — weekly goal tracking
    ixl compare     [--json]                    — side-by-side for all accounts.env children
    ixl notify      [--dry-run] [--json]        — send webhook notifications
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
    IXLSession,
    _ensure_dir,
    _escape_env_value,
    _log,
)
from ixl_cli.export import export_csv, export_html
from ixl_cli.goals import evaluate_goals, generate_defaults, load_goals, save_goals
from ixl_cli.history import _build_snapshot, compute_trends, load_snapshots, save_snapshot
from ixl_cli.scrapers.children import scrape_children
from ixl_cli.scrapers.diagnostics import scrape_diagnostics
from ixl_cli.scrapers.skills import scrape_skills
from ixl_cli.scrapers.trouble_spots import scrape_trouble_spots
from ixl_cli.scrapers.usage import scrape_usage


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------


def make_result(
    *,
    command: str,
    status: str = "ok",
    data=None,
    warnings: list[dict] | None = None,
    errors: list[dict] | None = None,
    exit_code: int = 0,
    summary: str | None = "Completed successfully.",
) -> dict:
    return {
        "command": command,
        "status": status,
        "data": data,
        "warnings": list(warnings or []),
        "errors": list(errors or []),
        "exit_code": exit_code,
        "summary": summary,
    }


def add_warning(result: dict, *, code: str, message: str, stage: str, retryable: bool) -> None:
    result["warnings"].append({
        "code": code,
        "message": message,
        "stage": stage,
        "retryable": retryable,
    })
    if result["status"] == "ok":
        result["status"] = "warning"


def add_error(result: dict, *, code: str, message: str, stage: str, retryable: bool) -> None:
    result["errors"].append({
        "code": code,
        "message": message,
        "stage": stage,
        "retryable": retryable,
    })
    result["status"] = "error"


def render_json_result(result: dict) -> dict:
    payload = result.get("data") or {}
    if not isinstance(payload, dict):
        payload = {"data": payload}
    return {
        "status": result["status"],
        "warnings": result["warnings"],
        "errors": result["errors"],
        **payload,
    }


def summarize_result(result: dict) -> str:
    if result.get("summary"):
        return result["summary"]
    status = result.get("status")
    if status == "ok":
        return "Completed successfully."
    if status == "warning":
        return f"Completed with warnings ({len(result.get('warnings', []))})."
    errors = result.get("errors", [])
    if errors:
        return f"Failed: {errors[0]['message']}."
    return "Failed."


def finalize_result(result: dict, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(render_json_result(result), indent=2))
    else:
        important_warnings = result.get("warnings", [])
        for warning in important_warnings:
            print(f"Warning [{warning['stage']}]: {warning['message']}", file=sys.stderr)
        print(summarize_result(result))
    return int(result.get("exit_code", 1))


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
        print("\n    Top categories:")
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


def output_compare(comparison: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(comparison, indent=2))
        return

    children = comparison.get("children", [])
    if not children:
        print("No comparison data found.")
        return

    print(f"\n{'Name':<25} {'Grade':<8} {'Mastered':<10} {'Excellent':<10} {'Trouble':<8} {'Minutes':<8}")
    print("-" * 80)
    for child in children:
        skills_summary = child.get("skills_summary", {})
        usage = child.get("usage", {})
        print(
            f"{child.get('name', ''):<25} "
            f"{child.get('grade', ''):<8} "
            f"{skills_summary.get('mastered', 0):<10} "
            f"{skills_summary.get('excellent', 0):<10} "
            f"{child.get('trouble_spot_count', 0):<8} "
            f"{usage.get('time_spent_min', 0):<8}"
        )
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


def cmd_children(args: argparse.Namespace) -> dict:
    session = IXLSession(verbose=not args.json)
    children = scrape_children(session)
    if not args.json:
        output_children(children, False)
    return make_result(command="children", data=children)


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


def cmd_assigned(args: argparse.Namespace) -> dict:
    session = IXLSession(verbose=not args.json)
    skills_data = scrape_skills(session, subject=args.subject)

    all_remaining: list[dict] = []
    totals: dict[str, dict] = {}
    for subj in skills_data:
        subject = subj.get("subject", "Unknown")
        assigned = [sk for sk in subj.get("skills", []) if sk.get("suggested")]
        done = [sk for sk in assigned if (sk.get("smart_score", 0) or 0) >= 80]
        not_started = [sk for sk in assigned if sk.get("questions", 0) == 0]
        in_progress = [
            sk for sk in assigned
            if sk.get("questions", 0) > 0 and (sk.get("smart_score", 0) or 0) < 80
        ]
        totals[subject] = {
            "assigned": len(assigned),
            "done": len(done),
            "in_progress": len(in_progress),
            "not_started": len(not_started),
            "remaining": len(not_started) + len(in_progress),
        }
        for sk in not_started + in_progress:
            all_remaining.append({**sk, "subject": subject})

    if getattr(args, "priority", False):
        all_remaining.sort(key=lambda sk: (
            0 if sk.get("questions", 0) == 0 else 1,
            sk.get("smart_score", 0) or 0,
        ))

    active_totals = {k: v for k, v in totals.items() if v["assigned"] > 0}

    if not args.json:
        output_assigned(skills_data, False)

    return make_result(command="assigned", data={"totals": active_totals, "remaining": all_remaining})


def cmd_goals(args: argparse.Namespace) -> dict:
    if args.init:
        session = IXLSession(verbose=True)
        _log("Generating goal defaults from last 14 days of usage...", True)

        usage = scrape_usage(session, days=14)
        skills_data = scrape_skills(session)
        defaults = generate_defaults(usage, skills_data)
        save_goals(defaults)

        if not args.json:
            print(f"\nGoals saved to {GOALS_PATH}")
            print(json.dumps(defaults, indent=2))
            print(f"\nEdit {GOALS_PATH} to adjust targets.")
        return make_result(command="goals", data={"goals": defaults})

    goals = load_goals()
    if goals is None:
        return make_result(
            command="goals",
            status="error",
            data={},
            errors=[{
                "code": "goals.config_missing",
                "message": "No goals configured. Run `ixl goals --init`.",
                "stage": "goals",
                "retryable": False,
            }],
            exit_code=2,
            summary=None,
        )

    session = IXLSession(verbose=not args.json)

    # Fetch current week's data (days since Monday)
    today = datetime.now()
    days_since_monday = today.weekday()  # 0=Mon
    usage = scrape_usage(session, days=days_since_monday + 1)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)

    goal_status = evaluate_goals(goals, usage, skills_data, trouble_spots)
    if not args.json:
        output_goals(goal_status, False)
    return make_result(command="goals", data={"goals": goal_status})


def _load_accounts() -> list[dict]:
    from ixl_cli.compare import load_accounts

    return load_accounts()


def _build_comparison(summaries: list[dict]) -> dict:
    from ixl_cli.compare import build_comparison

    return build_comparison(summaries)


def _load_notify_config() -> dict | None:
    from ixl_cli.notify import load_notify_config

    return load_notify_config()


def _notify_all(
    config: dict,
    summary: dict,
    goals: dict | None = None,
    dry_run: bool = False,
) -> list[dict]:
    from ixl_cli.notify import notify_all

    return notify_all(config, summary, goals, dry_run=dry_run)


def cmd_compare(args: argparse.Namespace) -> dict:
    accounts = _load_accounts()
    if not accounts:
        return make_result(
            command="compare",
            status="error",
            data={},
            errors=[{
                "code": "compare.accounts_missing",
                "message": "No accounts found. Create ~/.ixl/accounts.env.",
                "stage": "compare",
                "retryable": False,
            }],
            exit_code=2,
            summary=None,
        )

    summaries = []
    result = make_result(command="compare", data={"children": []})
    for acct in accounts:
        _log(f"Fetching data for {acct['name']}...", not args.json)
        os.environ["IXL_EMAIL"] = acct["email"]
        os.environ["IXL_PASSWORD"] = acct["password"]

        try:
            session = IXLSession(verbose=False)
            children = scrape_children(session)
            child = children[0] if children else None
            diagnostics = scrape_diagnostics(session)
            skills_data = scrape_skills(session)
            trouble_spots = scrape_trouble_spots(session)
            usage = scrape_usage(session)

            summaries.append({
                "student": child,
                "diagnostics": diagnostics,
                "skills": skills_data,
                "trouble_spots": trouble_spots,
                "usage": usage,
            })
        except Exception as e:
            add_warning(
                result,
                code="compare.account_failed",
                message=f"Failed to fetch data for {acct['name']}",
                stage="compare",
                retryable=True,
            )
            _log(f"  Error fetching {acct['name']}: {e}", True)

    comparison = _build_comparison(summaries)
    result["data"] = comparison
    if not summaries:
        add_error(
            result,
            code="compare.all_accounts_failed",
            message="Failed to fetch data for all accounts.",
            stage="compare",
            retryable=True,
        )
        result["exit_code"] = 1
        result["summary"] = None
    if not args.json:
        output_compare(comparison, False)
    return result


def cmd_notify(args: argparse.Namespace) -> dict:
    """Send notifications to configured webhooks."""
    config = _load_notify_config()
    if config is None:
        return make_result(
            command="notify",
            status="error",
            data={},
            errors=[{
                "code": "notify.config_missing",
                "message": "No notification config. Create ~/.ixl/notifications.json.",
                "stage": "notify",
                "retryable": False,
            }],
            exit_code=2,
            summary=None,
        )

    session = IXLSession(verbose=not args.json)
    children = scrape_children(session)
    child = children[0] if children else None
    diagnostics = scrape_diagnostics(session)
    skills_data = scrape_skills(session)
    trouble_spots = scrape_trouble_spots(session)
    usage = scrape_usage(session)

    summary = {
        "student": child,
        "diagnostics": diagnostics,
        "skills": skills_data,
        "trouble_spots": trouble_spots,
        "usage": usage,
    }

    goals_config = load_goals()
    goal_status = None
    if goals_config is not None:
        days_since_monday = datetime.now().weekday()
        week_usage = scrape_usage(session, days=days_since_monday + 1)
        goal_status = evaluate_goals(goals_config, week_usage, skills_data, trouble_spots)

    results = _notify_all(config, summary, goal_status, dry_run=args.dry_run)

    if not args.json:
        for r in results:
            status = "DRY RUN" if r.get("dry_run") else ("OK" if r["sent"] else "FAILED")
            print(f"  {r['format']:<10} {r['url'][:50]:<50} {status}")

    result = make_result(command="notify", data={"results": results})
    failed = [r for r in results if not r.get("dry_run") and not r.get("sent")]
    succeeded = [r for r in results if r.get("dry_run") or r.get("sent")]
    if failed and succeeded:
        add_warning(
            result,
            code="notify.delivery_failed",
            message=f"{len(failed)} notification deliveries failed.",
            stage="notify",
            retryable=True,
        )
    elif failed and not succeeded:
        add_error(
            result,
            code="notify.all_deliveries_failed",
            message="All notification deliveries failed.",
            stage="notify",
            retryable=True,
        )
        result["exit_code"] = 1
        result["summary"] = None
    return result


def cmd_summary(args: argparse.Namespace) -> dict:
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
        yesterday_snapshots = load_snapshots(days=1)
        trouble_baseline = yesterday_snapshots[-1]["trouble_spot_count"] if yesterday_snapshots else None
        goal_status = evaluate_goals(goals, week_usage, skills_data, trouble_spots, trouble_spot_baseline=trouble_baseline)

    # Auto-save snapshot for trend tracking (skip with --no-save)
    if not getattr(args, "no_save", False):
        save_snapshot(_build_snapshot(skills_data, trouble_spots, usage))

    # Export formats: print and return early
    fmt = getattr(args, "format", None)
    if fmt == "csv":
        print(export_csv({"skills": skills_data}, child), end="")
        return make_result(command="summary", data={})
    if fmt == "html":
        print(export_html({"skills": skills_data}, child), end="")
        return make_result(command="summary", data={})

    if not args.json:
        output_summary(child, children, diagnostics, skills_data, trouble_spots, usage, False, goal_status=goal_status)

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

    return make_result(command="summary", data=data)


def cmd_trends(args: argparse.Namespace) -> dict:
    """Show historical trends from saved snapshots."""
    snapshots = load_snapshots(days=args.days)
    if not snapshots:
        result = make_result(command="trends", data={"trends": {"datapoints": [], "deltas": {}}})
        add_warning(
            result,
            code="trends.no_data",
            message=f"No snapshots found for the last {args.days} days. Run `ixl summary` at least twice to build history.",
            stage="trends",
            retryable=False,
        )
        return result

    trends = compute_trends(snapshots)

    if not args.json:
        deltas = trends.get("deltas", {})
        print(f"\n  Trends (last {len(snapshots)} snapshots over {args.days} days):")
        labels = {
            "skills_mastered": "Skills mastered",
            "skills_excellent": "Skills excellent",
            "trouble_spot_count": "Trouble spots",
            "time_spent_min": "Time (min)",
            "questions_answered": "Questions answered",
            "days_active": "Days active",
        }
        for key, label in labels.items():
            if key in deltas:
                delta = deltas[key]
                sign = "+" if delta > 0 else ""
                print(f"    {label:<22} {sign}{delta}")
        print()

    return make_result(command="trends", data={"trends": trends})


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
    sp_assigned.add_argument("--priority", action="store_true", help="Sort remaining skills by urgency")
    sp_assigned.add_argument("--json", action="store_true", help="JSON output")
    sp_assigned.set_defaults(func=cmd_assigned)

    # ixl compare
    sp_compare = subparsers.add_parser("compare", help="Compare across student accounts")
    sp_compare.add_argument("--json", action="store_true", help="JSON output")
    sp_compare.set_defaults(func=cmd_compare)

    # ixl summary
    sp_sum = subparsers.add_parser("summary", help="Full summary (all data)")
    sp_sum.add_argument("--child", type=str, help="(ignored — for future multi-account use)")
    sp_sum.add_argument("--json", action="store_true", help="JSON output")
    sp_sum.add_argument("--format", choices=["json", "csv", "html"], help="Output format")
    sp_sum.add_argument("--no-save", action="store_true", help="Don't save snapshot for trend tracking")
    sp_sum.set_defaults(func=cmd_summary)

    # ixl notify
    sp_notify = subparsers.add_parser("notify", help="Send notifications via webhooks")
    sp_notify.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    sp_notify.add_argument("--json", action="store_true", help="JSON output")
    sp_notify.set_defaults(func=cmd_notify)

    # ixl goals
    sp_goals = subparsers.add_parser("goals", help="Weekly goal tracking")
    sp_goals.add_argument("--init", action="store_true", help="Generate goals from recent usage")
    sp_goals.add_argument("--json", action="store_true", help="JSON output")
    sp_goals.set_defaults(func=cmd_goals)

    # ixl trends
    sp_trends = subparsers.add_parser("trends", help="Show historical progress trends")
    sp_trends.add_argument("--days", type=int, default=30, help="Days to look back (default 30)")
    sp_trends.add_argument("--json", action="store_true", help="JSON output")
    sp_trends.set_defaults(func=cmd_trends)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        result = args.func(args)
        if result is None:
            result = make_result(command=args.command, data={})
        sys.exit(finalize_result(result, as_json=getattr(args, "json", False)))
    except RuntimeError as e:
        message = str(e)
        error_code = "runtime.error"
        exit_code = 1
        if message.startswith("No credentials found"):
            error_code = "config.credentials_missing"
            exit_code = 2
        result = make_result(
            command=args.command or "ixl",
            status="error",
            errors=[{
                "code": error_code,
                "message": message,
                "stage": args.command or "main",
                "retryable": False,
            }],
            exit_code=exit_code,
            summary=None,
        )
        sys.exit(finalize_result(result, as_json=getattr(args, "json", False)))
    except KeyboardInterrupt:
        sys.exit(130)
    except requests.RequestException as e:
        result = make_result(
            command=args.command or "ixl",
            status="error",
            errors=[{
                "code": "network.request_failed",
                "message": f"Network error: {e}",
                "stage": args.command or "main",
                "retryable": True,
            }],
            exit_code=1,
            summary=None,
        )
        sys.exit(finalize_result(result, as_json=getattr(args, "json", False)))


if __name__ == "__main__":
    main()
