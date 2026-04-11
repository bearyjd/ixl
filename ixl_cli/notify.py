"""
IXL notify — webhook notification dispatch.

Reads ~/.ixl/notifications.json and sends formatted summaries
to configured Slack or plain-text HTTP endpoints.
"""

import json

import requests

from ixl_cli.session import NOTIFICATIONS_PATH


def load_notify_config() -> dict | None:
    """Load webhook config from ~/.ixl/notifications.json.

    Returns None if the file is missing or malformed.
    """
    if not NOTIFICATIONS_PATH.exists():
        return None
    try:
        with open(NOTIFICATIONS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _format_plain(summary: dict, goals: dict | None) -> str:
    """Build a plain-text notification message."""
    student = summary.get("student") or {}
    name = student.get("name", "Student")
    grade = student.get("grade", "")
    usage = summary.get("usage") or {}
    trouble_spots = summary.get("trouble_spots") or []

    lines = [f"IXL Daily Report — {name}" + (f" (Grade {grade})" if grade else "")]
    lines.append("")
    lines.append(f"Time: {usage.get('time_spent_min', 0)} min  |  Questions: {usage.get('questions_answered', 0)}")
    lines.append(f"Trouble spots: {len(trouble_spots)}")

    if goals:
        lines.append("")
        lines.append("Goals:")
        for key, metric in goals.get("metrics", {}).items():
            status = metric.get("status", "no_data")
            actual = metric.get("actual", 0)
            target = metric.get("target", 0)
            lines.append(f"  {key}: {actual}/{target}  [{status}]")

    return "\n".join(lines)


def _format_slack(summary: dict, goals: dict | None) -> dict:
    """Build a Slack Block Kit payload."""
    student = summary.get("student") or {}
    name = student.get("name", "Student")
    grade = student.get("grade", "")
    usage = summary.get("usage") or {}
    trouble_spots = summary.get("trouble_spots") or []

    header = f"IXL Report — {name}" + (f" (Grade {grade})" if grade else "")
    stats = (
        f"*Time:* {usage.get('time_spent_min', 0)} min  "
        f"*Questions:* {usage.get('questions_answered', 0)}  "
        f"*Trouble spots:* {len(trouble_spots)}"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": stats}},
    ]

    if goals:
        goal_lines = []
        for key, metric in goals.get("metrics", {}).items():
            status = metric.get("status", "no_data")
            actual = metric.get("actual", 0)
            target = metric.get("target", 0)
            icon = {"ahead": "✅", "on_track": "🟡", "behind": "🔴"}.get(status, "⚪")
            goal_lines.append(f"{icon} {key}: {actual}/{target}")
        if goal_lines:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Goals:*\n" + "\n".join(goal_lines)},
            })

    return {"blocks": blocks}


def notify_all(
    config: dict,
    summary: dict,
    goals: dict | None = None,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Dispatch notifications to all configured webhooks.

    Returns a list of result dicts:
        [{"url": str, "format": str, "sent": bool, "dry_run": bool}]
    """
    results = []
    for webhook in config.get("webhooks", []):
        url = webhook.get("url", "")
        fmt = webhook.get("format", "plain")

        if dry_run:
            results.append({"url": url, "format": fmt, "sent": True, "dry_run": True})
            continue

        try:
            if fmt == "slack":
                payload = _format_slack(summary, goals)
                requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                ).raise_for_status()
            else:  # plain
                text = _format_plain(summary, goals)
                requests.post(
                    url,
                    data=text.encode(),
                    headers={"Content-Type": "text/plain"},
                    timeout=10,
                ).raise_for_status()
            results.append({"url": url, "format": fmt, "sent": True, "dry_run": False})
        except Exception:
            results.append({"url": url, "format": fmt, "sent": False, "dry_run": False})

    return results
