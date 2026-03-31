"""Tests for ixl_cli.scrapers.skills."""

from datetime import date
from unittest.mock import patch

from ixl_cli.scrapers.skills import scrape_skills, _discover_active_grades


class TestSchoolYearStartDate:
    """Bug #1: Hardcoded '2025-08-01' breaks after August 2026."""

    def test_school_year_start_is_dynamic_fall(self, mock_session):
        """In October 2026, school year start should be 2026-08-01."""
        calls = []

        def capture_fetch(path, params=None, **kw):
            if params and "startDate" in params:
                calls.append(params["startDate"])
            return {"grade": "4"}

        mock_session.fetch_json = capture_fetch

        with patch("ixl_cli.scrapers.skills.date") as mock_date:
            mock_date.today.return_value = date(2026, 10, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            scrape_skills(mock_session)

        assert calls, "No API calls captured"
        for start_date in calls:
            assert start_date == "2026-08-01", (
                f"Expected school year 2026-08-01, got {start_date}"
            )

    def test_school_year_start_is_dynamic_spring(self, mock_session):
        """In March 2027, school year start should still be 2026-08-01."""
        calls = []

        def capture_fetch(path, params=None, **kw):
            if params and "startDate" in params:
                calls.append(params["startDate"])
            return {"grade": "4"}

        mock_session.fetch_json = capture_fetch

        with patch("ixl_cli.scrapers.skills.date") as mock_date:
            mock_date.today.return_value = date(2027, 3, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            scrape_skills(mock_session)

        assert calls, "No API calls captured"
        for start_date in calls:
            assert start_date == "2026-08-01", (
                f"Expected school year 2026-08-01, got {start_date}"
            )


class TestGradeCache:
    """Bug #8: Monkey-patching session with setattr for grade cache."""

    def test_grade_cache_uses_dict_not_setattr(self, mock_session):
        """Grade cache should use session._cache dict, not setattr on session."""
        mock_session.fetch_json = lambda path, **kw: None

        _discover_active_grades(mock_session, 0, 4, "2026-08-01", "2027-03-15")

        # Should be stored in _cache dict, not as a bare attribute
        assert hasattr(mock_session, "_cache"), "Session should have _cache dict"
        assert "_active_grades_0" in mock_session._cache, (
            "Grade cache should be stored in _cache dict"
        )
        assert not hasattr(mock_session, "_active_grades_0"), (
            "Grade cache should NOT be set directly on session object"
        )


class TestGradeKindergarten:
    """Bug #12: int() crash on kindergarten grade 'K'."""

    def test_grade_k_no_crash(self, mock_session):
        """Non-numeric grade like 'K' should not crash with ValueError."""
        mock_session.fetch_json = lambda path, params=None, **kw: (
            {"grade": "K"} if "defaults" in path else None
        )

        # Should not raise ValueError
        result = scrape_skills(mock_session)
        assert isinstance(result, list)

    def test_grade_pk_no_crash(self, mock_session):
        """Pre-K grade should not crash."""
        mock_session.fetch_json = lambda path, params=None, **kw: (
            {"grade": "PK"} if "defaults" in path else None
        )

        result = scrape_skills(mock_session)
        assert isinstance(result, list)
