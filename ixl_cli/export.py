"""
IXL export — CSV and HTML export of summary data.

Used by `ixl summary --format csv` and `--format html`.
Both functions return strings suitable for writing to stdout or a file.
"""

import csv
import html as html_lib
import io


_CSV_FIELDS = ["Student", "Grade", "Subject", "Skill", "SkillCode",
               "SmartScore", "TimeMin", "Questions", "LastPracticed"]


def export_csv(data: dict, child: dict | None) -> str:
    """Return a CSV string with one row per skill across all subjects."""
    student_name = (child or {}).get("name", "")
    student_grade = (child or {}).get("grade", "")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()

    for subj in data.get("skills", []):
        subject = subj.get("subject", "")
        for sk in subj.get("skills", []):
            writer.writerow({
                "Student": student_name,
                "Grade": student_grade,
                "Subject": subject,
                "Skill": sk.get("name", ""),
                "SkillCode": sk.get("skill_code", ""),
                "SmartScore": sk.get("smart_score", ""),
                "TimeMin": sk.get("time_spent_min", ""),
                "Questions": sk.get("questions", ""),
                "LastPracticed": sk.get("last_practiced", ""),
            })

    return buf.getvalue()


def _score_class(score) -> str:
    if score is None:
        return "score-none"
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "score-none"
    if s >= 90:
        return "score-mastered"
    if s >= 80:
        return "score-excellent"
    if s >= 60:
        return "score-good"
    return "score-low"


_HTML_CSS = """
body { font-family: sans-serif; margin: 2rem; color: #222; }
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
table { border-collapse: collapse; width: 100%; margin-top: 0.75rem; font-size: 0.88rem; }
th { background: #f0f0f0; padding: 6px 10px; text-align: left; border: 1px solid #ccc; }
td { padding: 5px 10px; border: 1px solid #e0e0e0; }
tr:nth-child(even) { background: #fafafa; }
.score-mastered { background: #d4edda; font-weight: bold; }
.score-excellent { background: #fff3cd; }
.score-good { background: #f8f9fa; }
.score-low { background: #f8d7da; }
.score-none { color: #999; }
"""


def export_html(data: dict, child: dict | None) -> str:
    """Return a self-contained HTML file with color-coded SmartScore table."""
    e = html_lib.escape
    student_name = e((child or {}).get("name", "Student"))
    student_grade = (child or {}).get("grade", "")
    grade_label = f" — Grade {e(student_grade)}" if student_grade else ""

    rows_html = []
    for subj in data.get("skills", []):
        subject = e(subj.get("subject", ""))
        for sk in subj.get("skills", []):
            score = sk.get("smart_score")
            cls = _score_class(score)
            rows_html.append(
                f'<tr>'
                f'<td>{subject}</td>'
                f'<td>{e(sk.get("name", ""))}</td>'
                f'<td>{e(str(sk.get("skill_code", "")))}</td>'
                f'<td class="{cls}">{e(str(score if score is not None else ""))}</td>'
                f'<td>{e(str(sk.get("time_spent_min", "")))}</td>'
                f'<td>{e(str(sk.get("questions", "")))}</td>'
                f'<td>{e(str(sk.get("last_practiced", "")))}</td>'
                f'</tr>'
            )

    table_rows = "\n".join(rows_html) if rows_html else '<tr><td colspan="7">No skills recorded.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>IXL Report — {student_name}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>IXL Report — {student_name}{grade_label}</h1>
<table>
<thead>
<tr><th>Subject</th><th>Skill</th><th>Code</th><th>SmartScore</th><th>Min</th><th>Questions</th><th>Last Practiced</th></tr>
</thead>
<tbody>
{table_rows}
</tbody>
</table>
</body>
</html>
"""
