"""Unit tests for IXL scrapers: children, diagnostics, trouble_spots, usage."""

from argparse import Namespace
from unittest.mock import patch

from ixl_cli.scrapers.children import scrape_children
from ixl_cli.scrapers.diagnostics import scrape_diagnostics
from ixl_cli.scrapers.trouble_spots import scrape_trouble_spots
from ixl_cli.scrapers.usage import scrape_usage
from tests.conftest import make_response


class TestScrapeChildren:
    def test_returns_list_with_one_child(self, mock_session):
        ts_resp = make_response(200, {"firstName": "Ford", "lastName": "Smith", "table": []})
        grid_resp = make_response(200, {"grade": 3})
        with patch.object(mock_session.s, "request", side_effect=[ts_resp, grid_resp]):
            result = scrape_children(mock_session)
        assert len(result) == 1
        assert result[0]["name"] == "Ford Smith"
        assert result[0]["uid"] == "self"
        assert result[0]["grade"] == "3"

    def test_falls_back_to_username_when_no_name(self, mock_session):
        ts_resp = make_response(200, {"table": []})  # no firstName/lastName
        grid_resp = make_response(200, {"grade": 5})
        with patch.object(mock_session.s, "request", side_effect=[ts_resp, grid_resp]):
            result = scrape_children(mock_session)
        assert len(result) == 1
        assert result[0]["name"] != ""  # falls back to username

    def test_returns_one_item_even_when_api_fails(self, mock_session):
        err_resp = make_response(500, {})
        grid_resp = make_response(200, {})
        with patch.object(mock_session.s, "request", side_effect=[err_resp, grid_resp]):
            result = scrape_children(mock_session)
        assert len(result) == 1

    def test_uid_is_always_self(self, mock_session):
        ts_resp = make_response(200, {"firstName": "Alice", "lastName": "Wonder", "table": []})
        grid_resp = make_response(200, {"grade": 4})
        with patch.object(mock_session.s, "request", side_effect=[ts_resp, grid_resp]):
            result = scrape_children(mock_session)
        assert result[0]["uid"] == "self"


class TestScrapeDiagnostics:
    def test_returns_list_with_subject_data(self, mock_session):
        api_data = {
            "diagnosticGrowthOverTime": {
                "gradeLevel": {"abbreviatedPageTitle": "3rd grade"},
                "diagnosticGrowthData": [
                    {
                        "subjectInt": 0,
                        "maxPossibleScore": 1400,
                        "data": [
                            {"date": "2026-04-01", "diagnosticScore": 850, "gradeEquivalent": "3.5"}
                        ],
                    }
                ],
            }
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_diagnostics(mock_session)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["subject"] == "Math"
        assert result[0]["has_data"] is True
        assert result[0]["max_score"] == 1400

    def test_returns_empty_list_when_api_fails(self, mock_session):
        err_resp = make_response(500, {})
        with patch.object(mock_session.s, "request", return_value=err_resp):
            result = scrape_diagnostics(mock_session)
        assert result == []

    def test_returns_empty_list_when_no_growth_data(self, mock_session):
        api_data = {
            "diagnosticGrowthOverTime": {
                "gradeLevel": {},
                "diagnosticGrowthData": [],
            }
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_diagnostics(mock_session)
        assert result == []

    def test_last_assessed_populated(self, mock_session):
        api_data = {
            "diagnosticGrowthOverTime": {
                "gradeLevel": {},
                "diagnosticGrowthData": [
                    {
                        "subjectInt": 1,
                        "maxPossibleScore": 1200,
                        "data": [
                            {"date": "2026-03-15", "diagnosticScore": 700, "gradeEquivalent": "2.8"}
                        ],
                    }
                ],
            }
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_diagnostics(mock_session)
        assert result[0]["last_assessed"] == "2026-03-15"


class TestScrapeTroubleSpots:
    def test_returns_list_of_trouble_spots(self, mock_session):
        api_data = {
            "table": [
                {
                    "permacode": "F62",
                    "skillName": "Do you have enough money?",
                    "skillCode": "AA.11",
                    "gradeShortOrdinal": "2nd",
                    "numberOfIncorrectAnswers": 22,
                    "students": [{"score": 93}],
                }
            ]
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_trouble_spots(mock_session)
        assert isinstance(result, list)
        assert len(result) == 1
        spot = result[0]
        assert spot["name"] == "Do you have enough money?"
        assert spot["missed_count"] == 22
        assert spot["score"] == 93

    def test_returns_empty_when_no_trouble_spots_status(self, mock_session):
        api_data = {"status": "NO_TROUBLE_SPOTS"}
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_trouble_spots(mock_session)
        assert result == []

    def test_returns_empty_when_api_fails_and_fallback_fails(self, mock_session):
        err_resp1 = make_response(500, {})
        err_resp2 = make_response(500, {})
        with patch.object(mock_session.s, "request", side_effect=[err_resp1, err_resp2]):
            result = scrape_trouble_spots(mock_session)
        assert result == []

    def test_skill_fields_mapped_correctly(self, mock_session):
        api_data = {
            "table": [
                {
                    "permacode": "X99",
                    "skillName": "Multiply fractions",
                    "skillCode": "BB.5",
                    "gradeShortOrdinal": "5th",
                    "numberOfIncorrectAnswers": 10,
                    "students": [{"score": 55}],
                }
            ]
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_trouble_spots(mock_session)
        assert result[0]["skill"] == "X99"
        assert result[0]["skill_code"] == "BB.5"
        assert result[0]["grade"] == "5th"


class TestScrapeUsage:
    def test_returns_dict_with_usage_fields(self, mock_session):
        api_data = {
            "summary": {
                "practiceTimeSpent": 2700,  # 45 minutes
                "questionsAnswered": 187,
                "numSkills": 12,
            },
            "table": [
                {
                    "sessionStartLocalDateStr": "2026-04-10",
                    "secondsSpent": 1800,
                    "questionsAnswered": 90,
                    "numSkills": 6,
                    "skills": [],
                },
                {
                    "sessionStartLocalDateStr": "2026-04-11",
                    "secondsSpent": 900,
                    "questionsAnswered": 97,
                    "numSkills": 6,
                    "skills": [],
                },
            ],
            "categories": [],
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_usage(mock_session)
        assert isinstance(result, dict)
        assert result["time_spent_min"] == 45.0
        assert result["questions_answered"] == 187
        assert result["days_active"] == 2
        assert result["skills_practiced"] == 12

    def test_returns_zeroed_dict_when_api_fails(self, mock_session):
        err_resp = make_response(500, {})
        with patch.object(mock_session.s, "request", return_value=err_resp):
            result = scrape_usage(mock_session)
        assert isinstance(result, dict)
        assert result["time_spent_min"] == 0
        assert result["questions_answered"] == 0

    def test_accepts_days_parameter(self, mock_session):
        api_data = {
            "summary": {"practiceTimeSpent": 0, "questionsAnswered": 0, "numSkills": 0},
            "table": [],
            "categories": [],
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_usage(mock_session, days=14)
        assert result["period"] == "last_14_days"

    def test_days_active_counts_unique_dates(self, mock_session):
        api_data = {
            "summary": {"practiceTimeSpent": 0, "questionsAnswered": 0, "numSkills": 0},
            "table": [
                {"sessionStartLocalDateStr": "2026-04-10", "secondsSpent": 0, "questionsAnswered": 0, "numSkills": 0, "skills": []},
                {"sessionStartLocalDateStr": "2026-04-10", "secondsSpent": 0, "questionsAnswered": 0, "numSkills": 0, "skills": []},
                {"sessionStartLocalDateStr": "2026-04-11", "secondsSpent": 0, "questionsAnswered": 0, "numSkills": 0, "skills": []},
            ],
            "categories": [],
        }
        with patch.object(mock_session.s, "request", return_value=make_response(200, api_data)):
            result = scrape_usage(mock_session)
        assert result["days_active"] == 2  # two unique dates


class TestCmdAssigned:
    def _skills_data(self):
        return [
            {
                "subject": "Math",
                "skills": [
                    {"name": "A", "suggested": True, "smart_score": 45, "questions": 10},
                    {"name": "B", "suggested": True, "smart_score": 0, "questions": 0},
                    {"name": "C", "suggested": True, "smart_score": 70, "questions": 20},
                    {"name": "D", "suggested": True, "smart_score": 90, "questions": 50},  # done
                ],
            }
        ]

    def test_priority_puts_not_started_first(self):
        from ixl_cli.cli import cmd_assigned

        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=self._skills_data()),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=True))
        remaining = result["data"]["remaining"]
        assert remaining[0]["name"] == "B"  # not started
        assert remaining[1]["name"] == "A"  # in-progress low score
        assert remaining[2]["name"] == "C"  # in-progress higher score

    def test_no_priority_preserves_insertion_order(self):
        from ixl_cli.cli import cmd_assigned

        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=self._skills_data()),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=False))
        remaining = result["data"]["remaining"]
        names = [r["name"] for r in remaining]
        # not_started (B) + in_progress (A, C) in original order
        assert "A" in names
        assert "B" in names
        assert "C" in names
        assert "D" not in names  # done (score >= 80)

    def test_returns_result_dict(self):
        from ixl_cli.cli import cmd_assigned

        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=[]),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=False))
        assert isinstance(result, dict)
        assert "status" in result
        assert "exit_code" in result
        assert "data" in result

    def test_totals_computed_correctly(self):
        from ixl_cli.cli import cmd_assigned

        with (
            patch("ixl_cli.cli.IXLSession", return_value=object()),
            patch("ixl_cli.cli.scrape_skills", return_value=self._skills_data()),
            patch("builtins.print"),
        ):
            result = cmd_assigned(Namespace(json=False, subject=None, priority=False))
        totals = result["data"]["totals"]["Math"]
        assert totals["assigned"] == 4
        assert totals["done"] == 1
        assert totals["not_started"] == 1
        assert totals["in_progress"] == 2
        assert totals["remaining"] == 3
