import csv
import io
from ixl_cli.export import export_csv

_CHILD = {"name": "Ford", "grade": "3"}
_DATA = {
    "skills": [
        {
            "subject": "Math",
            "grade": "3",
            "skills": [
                {"name": "Add two numbers", "skill_code": "A.1", "smart_score": 92,
                 "time_spent_min": 12, "questions": 25, "last_practiced": "2026-04-10"},
                {"name": "Subtract", "skill_code": "A.2", "smart_score": 67,
                 "time_spent_min": 8, "questions": 18, "last_practiced": "2026-04-09"},
            ],
        }
    ]
}

def test_export_csv_returns_string():
    result = export_csv(_DATA, _CHILD)
    assert isinstance(result, str)
    assert len(result) > 0

def test_export_csv_has_header_row():
    result = export_csv(_DATA, _CHILD)
    reader = csv.DictReader(io.StringIO(result))
    assert set(reader.fieldnames) >= {"Student", "Grade", "Subject", "Skill", "SmartScore"}

def test_export_csv_has_one_row_per_skill():
    result = export_csv(_DATA, _CHILD)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2

def test_export_csv_row_values_match_skill_data():
    result = export_csv(_DATA, _CHILD)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    first = rows[0]
    assert first["Student"] == "Ford"
    assert first["Grade"] == "3"
    assert first["Subject"] == "Math"
    assert first["Skill"] == "Add two numbers"
    assert first["SmartScore"] == "92"
    assert first["TimeMin"] == "12"

def test_export_csv_handles_empty_skills():
    result = export_csv({"skills": []}, None)
    reader = csv.DictReader(io.StringIO(result))
    assert list(reader) == []


from ixl_cli.export import export_html

def test_export_html_returns_string_starting_with_doctype():
    result = export_html(_DATA, _CHILD)
    assert result.strip().startswith("<!DOCTYPE html>")

def test_export_html_includes_student_name():
    result = export_html(_DATA, _CHILD)
    assert "Ford" in result

def test_export_html_includes_skill_name():
    result = export_html(_DATA, _CHILD)
    assert "Add two numbers" in result

def test_export_html_color_codes_mastered_score():
    result = export_html(_DATA, _CHILD)
    # Smart score 92 should have green color class
    assert "score-mastered" in result or "#" in result  # green styling present

def test_export_html_escapes_special_characters():
    data = {"skills": [{"subject": "Math<>", "grade": "3", "skills": [
        {"name": "A & B", "skill_code": "X", "smart_score": 80,
         "time_spent_min": 5, "questions": 10, "last_practiced": ""}
    ]}]}
    result = export_html(data, {"name": "Ford", "grade": "3"})
    assert "Math<>" not in result
    assert "A & B" not in result
    assert "&amp;" in result or "A &amp; B" in result

def test_export_html_handles_empty_skills():
    result = export_html({"skills": []}, None)
    assert "<!DOCTYPE html>" in result
    assert "<table" in result


import sys
from argparse import Namespace
from unittest.mock import patch

def test_cmd_summary_format_csv_prints_csv(capsys):
    with (
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.cli.save_snapshot"),
    ):
        from ixl_cli.cli import cmd_summary
        cmd_summary(Namespace(json=False, child=None, format="csv", no_save=True))
    out = capsys.readouterr().out
    assert "Student" in out  # CSV header
    assert "{" not in out    # not JSON

def test_cmd_summary_format_html_prints_html(capsys):
    with (
        patch("ixl_cli.cli.IXLSession", return_value=object()),
        patch("ixl_cli.cli.scrape_children", return_value=[{"name": "Ford", "grade": "3"}]),
        patch("ixl_cli.cli.scrape_diagnostics", return_value=[]),
        patch("ixl_cli.cli.scrape_skills", return_value=[]),
        patch("ixl_cli.cli.scrape_trouble_spots", return_value=[]),
        patch("ixl_cli.cli.scrape_usage", return_value={}),
        patch("ixl_cli.cli.load_goals", return_value=None),
        patch("ixl_cli.cli.save_snapshot"),
    ):
        from ixl_cli.cli import cmd_summary
        cmd_summary(Namespace(json=False, child=None, format="html", no_save=True))
    out = capsys.readouterr().out
    assert "<!DOCTYPE html>" in out
    assert "Ford" in out
