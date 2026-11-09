
import pytest
import src.analytics.queries as queries


@pytest.fixture
def mock_execute_query(monkeypatch):
    """Capture both SQL queries and their parameters."""
    captured = []

    def fake_execute_query(sql, params):
        captured.append({
            "sql": sql,
            "params": params,
        })
        return []

    monkeypatch.setattr(
        queries, "execute_query", fake_execute_query
    )

    return captured


def get_where_clause(sql):
    """Extract the query-level WHERE clause."""
    before_group_by = sql.split("GROUP BY", 1)[0]
    return before_group_by.rsplit("WHERE", 1)[1].strip()


def test_weather_basic_call(mock_execute_query):
    result = queries.weather_risk_profile(
        airports=["JFK"]
    )

    assert len(mock_execute_query) == 2
    assert result["metadata"]["grain"] == "airport-hour"
    assert "summary" in result
    assert "hourly_coverage" in result
    assert "thresholds" in result


def test_weekday_filter(mock_execute_query):
    queries.weather_risk_profile(day_type="weekday")

    for query in mock_execute_query:
        assert (
            "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5"
            in query["sql"]
        )


def test_weekend_filter(mock_execute_query):
    queries.weather_risk_profile(day_type="weekend")

    for query in mock_execute_query:
        assert (
            "EXTRACT(ISODOW FROM hour_et) IN (6, 7)"
            in query["sql"]
        )


def test_specific_days_filter(mock_execute_query):
    result = queries.weather_risk_profile(
        day_type="weekday",
        days_of_week=["Monday", "Friday"],
    )

    for query in mock_execute_query:
        assert (
            "EXTRACT(ISODOW FROM hour_et) IN (?, ?)"
            in query["sql"]
        )

    # Summary parameters contain six thresholds first.
    assert 1 in mock_execute_query[0]["params"][6:]
    assert 5 in mock_execute_query[0]["params"][6:]

    assert result["filters"]["days_of_week"] == [
        "Monday", "Friday"
    ]


def test_hour_filter(mock_execute_query):
    result = queries.weather_risk_profile(
        start_hour=8,
        end_hour=12,
    )

    for query in mock_execute_query:
        assert "EXTRACT(HOUR FROM hour_et) >= ?" in query["sql"]
        assert "EXTRACT(HOUR FROM hour_et) < ?" in query["sql"]

    assert 8 in mock_execute_query[1]["params"]
    assert 12 in mock_execute_query[1]["params"]

    assert result["filters"]["start_hour"] == 8
    assert result["filters"]["end_hour"] == 12


def test_combined_temporal_filters(mock_execute_query):
    queries.weather_risk_profile(
        day_type="weekday",
        start_hour=8,
        end_hour=12,
    )

    summary = mock_execute_query[0]
    coverage = mock_execute_query[1]

    # Both queries must apply exactly the same WHERE conditions.
    assert get_where_clause(summary["sql"]) == get_where_clause(
        coverage["sql"]
    )

    # The summary query has six threshold parameters first.
    assert summary["params"][6:] == coverage["params"]


def test_returned_filter_metadata(mock_execute_query):
    result = queries.weather_risk_profile(
        day_type="weekday",
        days_of_week=["Monday", "Friday"],
        start_hour=8,
        end_hour=12,
    )

    assert result["filters"]["day_type"] == "weekday"
    assert result["filters"]["days_of_week"] == [
        "Monday", "Friday"
    ]
    assert result["filters"]["start_hour"] == 8
    assert result["filters"]["end_hour"] == 12


def test_invalid_day(mock_execute_query):
    with pytest.raises(ValueError):
        queries.weather_risk_profile(
            days_of_week=["Funday"]
        )


def test_incompatible_day_type(mock_execute_query):
    with pytest.raises(ValueError):
        queries.weather_risk_profile(
            day_type="weekend",
            days_of_week=["Monday"],
        )


def test_invalid_hour_range(mock_execute_query):
    with pytest.raises(ValueError):
        queries.weather_risk_profile(
            start_hour=12,
            end_hour=8,
        )


def test_invalid_hour_value(mock_execute_query):
    with pytest.raises(ValueError):
        queries.weather_risk_profile(
            start_hour=25,
            end_hour=26,
        )


def test_variable_specific_denominators(mock_execute_query):
    queries.weather_risk_profile()

    sql = mock_execute_query[0]["sql"]

    assert "NULLIF(COUNT(visibility_km), 0)" in sql
    assert "NULLIF(COUNT(precipitation_mm), 0)" in sql
    assert "NULLIF(COUNT(wind_speed_m_s), 0)" in sql


def test_precipitation_trace_caveat(mock_execute_query):
    result = queries.weather_risk_profile()

    assert any(
        "Precipitation traces" in note
        for note in result["interpretation_notes"]
    )


def test_both_queries_use_same_temporal_parameters(mock_execute_query):
    queries.weather_risk_profile(
        day_type="weekday",
        days_of_week=["Monday", "Friday"],
        start_hour=7,
        end_hour=11,
    )

    summary_params = mock_execute_query[0]["params"]
    coverage_params = mock_execute_query[1]["params"]

    assert summary_params[6:] == coverage_params
