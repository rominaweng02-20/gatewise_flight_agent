
import pytest

import src.analytics.queries as queries


@pytest.fixture
def mock_execute_query(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params

        return [
            {
                "airport": "JFK",
                "scheduled_flights": 100,
                "cancellations": 5,
                "departed_flights": 95,
                "delay_observations": 90,
                "classified_departed_flights": 90,
                "flights_15min_late": 30,
                "departure_15min_late_rate": 30 / 90,
            }
        ]

    monkeypatch.setattr(queries, "execute_query", fake_execute_query)
    return captured


def test_flight_basic_call(mock_execute_query):
    result = queries.flight_reliability(
        airports=["JFK"],
        grain="daily",
    )

    assert result["metadata"]["grain"] == "airport-day"
    assert result["filters"]["grain"] == "daily"
    assert len(result["rows"]) == 1


def test_15_minute_metric_and_denominator(mock_execute_query):
    result = queries.flight_reliability(grain="daily")

    sql = mock_execute_query["sql"]

    assert "flights_15min_late" in sql
    assert "classified_departed_flights" in sql
    assert "flights_30min_late" not in sql
    assert "departure_15min_late_rate" in sql

    assert result["interpretation_notes"]


def test_weekday_filter(mock_execute_query):
    queries.flight_reliability(
        grain="daily",
        day_type="weekday",
    )

    assert (
        "EXTRACT(ISODOW FROM date) BETWEEN 1 AND 5"
        in mock_execute_query["sql"]
    )


def test_weekend_filter(mock_execute_query):
    queries.flight_reliability(
        grain="daily",
        day_type="weekend",
    )

    assert (
        "EXTRACT(ISODOW FROM date) IN (6, 7)"
        in mock_execute_query["sql"]
    )


def test_specific_days_filter(mock_execute_query):
    result = queries.flight_reliability(
        grain="daily",
        day_type="weekday",
        days_of_week=["Monday", "Friday"],
    )

    assert (
        "EXTRACT(ISODOW FROM date) IN (?, ?)"
        in mock_execute_query["sql"]
    )

    assert 1 in mock_execute_query["params"]
    assert 5 in mock_execute_query["params"]

    assert result["filters"]["days_of_week"] == [
        "Monday", "Friday"
    ]


def test_hourly_uses_scheduled_departure_hour(mock_execute_query):
    queries.flight_reliability(
        grain="hourly",
        start_hour=8,
        end_hour=12,
    )

    sql = mock_execute_query["sql"]

    assert "scheduled_departure_hour >= ?" in sql
    assert "scheduled_departure_hour < ?" in sql
    assert "scheduled_departure_hour >=" in sql
    assert 8 in mock_execute_query["params"]
    assert 12 in mock_execute_query["params"]


def test_hourly_uses_local_scheduled_datetime_for_weekday(mock_execute_query):
    queries.flight_reliability(
        grain="hourly",
        day_type="weekday",
    )

    assert (
        "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5"
        in mock_execute_query["sql"]
    )


def test_daily_rejects_hour_filters(mock_execute_query):
    with pytest.raises(ValueError):
        queries.flight_reliability(
            grain="daily",
            start_hour=8,
        )


def test_monthly_grain(mock_execute_query):
    result = queries.flight_reliability(
        grain="monthly",
        day_type="weekday",
    )

    sql = mock_execute_query["sql"]

    assert "DATE_TRUNC('month', date)" in sql
    assert "SUM(flights_15min_late)" in sql
    assert "SUM(classified_departed_flights)" in sql
    assert result["metadata"]["grain"] == "airport-month"


def test_invalid_grain(mock_execute_query):
    with pytest.raises(ValueError):
        queries.flight_reliability(grain="weekly")


def test_invalid_day(mock_execute_query):
    with pytest.raises(ValueError):
        queries.flight_reliability(
            days_of_week=["Funday"]
        )


def test_incompatible_day_type(mock_execute_query):
    with pytest.raises(ValueError):
        queries.flight_reliability(
            day_type="weekend",
            days_of_week=["Monday"],
        )
