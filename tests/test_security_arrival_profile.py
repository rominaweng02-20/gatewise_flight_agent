
import pytest

import src.analytics.queries as queries


@pytest.fixture
def mock_execute_query(monkeypatch):
    """Prevent tests from connecting to the actual database."""
    captured = {}

    def fake_execute_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [
            {
                "airport": "JFK",
                "queue_type": "standard",
                "p50_wait_min": 12.0,
                "p90_wait_min": 25.0,
                "mean_wait_min": 14.0,
                "observed_hours": 100,
                "observed_days": 20,
            }
        ]

    monkeypatch.setattr(queries, "execute_query", fake_execute_query)
    return captured


def test_security_basic_call(mock_execute_query):
    """Basic call should return results and expected metadata."""

    result = queries.security_arrival_profile(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-08-31",
    )

    assert result["metadata"]["airports"] == ["JFK"]
    assert result["filters"]["day_type"] == "all"
    assert result["filters"]["queue_type"] == "standard"
    assert len(result["summary"]) == 1
    assert result["summary"][0]["airport"] == "JFK"


def test_security_weekdays_only(mock_execute_query):
    """Weekday selection should appear in the SQL."""

    queries.security_arrival_profile(
        airports=["JFK"],
        day_type="weekday",
    )

    sql = mock_execute_query["sql"]

    assert "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5" in sql


def test_security_specific_days(mock_execute_query):
    """Specific days should narrow the query to those weekdays."""

    result = queries.security_arrival_profile(
        airports=["JFK"],
        day_type="weekday",
        days_of_week=["Monday", "Friday"],
    )

    sql = mock_execute_query["sql"]
    params = mock_execute_query["params"]

    assert "EXTRACT(ISODOW FROM hour_et) IN (?, ?)" in sql
    assert 1 in params  # Monday
    assert 5 in params  # Friday
    assert result["filters"]["days_of_week"] == ["Monday", "Friday"]


def test_security_weekend_filter(mock_execute_query):
    """Weekend should include Saturday and Sunday."""

    queries.security_arrival_profile(
        airports=["JFK"],
        day_type="weekend",
    )

    sql = mock_execute_query["sql"]

    assert "EXTRACT(ISODOW FROM hour_et) IN (6, 7)" in sql


def test_security_hour_filter(mock_execute_query):
    """Hour range should use an inclusive start and exclusive end."""

    queries.security_arrival_profile(
        airports=["JFK"],
        start_hour=8,
        end_hour=12,
    )

    sql = mock_execute_query["sql"]
    params = mock_execute_query["params"]

    assert "EXTRACT(HOUR FROM hour_et) >= ?" in sql
    assert "EXTRACT(HOUR FROM hour_et) < ?" in sql
    assert 8 in params
    assert 12 in params


def test_security_rejects_invalid_hour(mock_execute_query):
    with pytest.raises(ValueError):
        queries.security_arrival_profile(
            start_hour=25
        )


def test_security_rejects_invalid_end_hour(mock_execute_query):
    with pytest.raises(ValueError):
        queries.security_arrival_profile(
            end_hour=25
        )


def test_security_rejects_reversed_hour_range(mock_execute_query):
    with pytest.raises(ValueError):
        queries.security_arrival_profile(
            start_hour=15,
            end_hour=10,
        )


def test_security_rejects_incompatible_days(mock_execute_query):
    """Monday cannot be selected with weekend-only filtering."""

    with pytest.raises(ValueError):
        queries.security_arrival_profile(
            day_type="weekend",
            days_of_week=["Monday"],
        )


def test_security_rejects_invalid_day(mock_execute_query):
    with pytest.raises(ValueError):
        queries.security_arrival_profile(
            days_of_week=["Funday"],
        )
