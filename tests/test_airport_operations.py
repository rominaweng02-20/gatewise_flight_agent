
import pytest

from src.analytics import queries


@pytest.fixture
def mock_execute_query(monkeypatch):
    """Capture SQL calls and return controlled query results."""
    calls = []

    def fake_execute_query(sql, params):
        calls.append({
            "sql": sql,
            "params": params,
        })

        # First query: daily airport operations
        if len(calls) == 1:
            return [
                {
                    "airport": "JFK",
                    "date": "2026-04-01",
                    "total_ops": 1000,
                    "total_delays": 100,
                    "delays_per_100_ops": 10.0,
                    "avg_delay_minutes": 25,
                    "total_delay_minutes": 2500,
                    "cause_weather": 40,
                    "cause_volume": 30,
                    "cause_equipment": 15,
                    "cause_runway": 10,
                    "cause_other": 5,
                    "tmi_to_delays": 20,
                    "occurred_dep_delays": 50,
                    "occurred_abrn_delays": 30,
                    "tmi_from_local_delays": 10,
                    "tmi_from_nonlocal_delays": 5,
                }
            ]

        # Second query: airport-level summary
        return [
            {
                "airport": "JFK",
                "total_ops": 1000,
                "total_delays": 100,
                "period_delays_per_100_ops": 10.0,
                "total_delay_minutes": 2500,
                "weather_delays": 40,
                "volume_delays": 30,
                "equipment_delays": 15,
                "runway_delays": 10,
                "other_delays": 5,
            }
        ]

    monkeypatch.setattr(
        queries,
        "execute_query",
        fake_execute_query,
    )

    return calls


def test_basic_call(mock_execute_query):
    result = queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    assert isinstance(result, dict)
    assert "metadata" in result
    assert "summary" in result
    assert "daily_rows" in result
    assert "interpretation_notes" in result

    # The function should execute two queries.
    assert len(mock_execute_query) == 2


def test_daily_query_contains_expected_columns(mock_execute_query):
    queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    sql = mock_execute_query[0]["sql"].lower()

    expected_columns = [
        "airport",
        "date",
        "total_ops",
        "total_delays",
        "delays_per_100_ops",
        "avg_delay_minutes",
        "total_delay_minutes",
        "cause_weather",
        "cause_volume",
        "cause_equipment",
        "cause_runway",
        "cause_other",
    ]

    for column in expected_columns:
        assert column in sql

    assert "from faa_operations_daily" in sql
    assert "order by airport, date" in sql


def test_summary_uses_weighted_delay_rate(mock_execute_query):
    queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    summary_sql = mock_execute_query[1]["sql"].lower()

    # Period rate must be based on summed counts.
    assert "sum(total_delays)" in summary_sql
    assert "sum(total_ops)" in summary_sql
    assert "nullif(sum(total_ops), 0)" in summary_sql

    # It should not average daily delay rates.
    assert "avg(delays_per_100_ops)" not in summary_sql

    assert "group by airport" in summary_sql
    assert "order by airport" in summary_sql


def test_both_queries_use_same_filters(mock_execute_query):
    queries.airport_operations(
        airports=["JFK", "LGA"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    daily_call = mock_execute_query[0]
    summary_call = mock_execute_query[1]

    # Both queries must use identical parameters.
    assert daily_call["params"] == summary_call["params"]

    # Extract only the WHERE clause, excluding grouping and ordering.
    daily_where = (
        daily_call["sql"]
        .split("WHERE", 1)[1]
        .split("ORDER BY", 1)[0]
        .strip()
    )

    summary_where = (
        summary_call["sql"]
        .split("WHERE", 1)[1]
        .split("GROUP BY", 1)[0]
        .strip()
    )

    assert daily_where == summary_where


def test_leading_delay_causes_are_sorted(mock_execute_query):
    result = queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    causes = result["summary"][0]["leading_delay_causes"]

    assert causes == [
        {"cause": "weather", "delays": 40},
        {"cause": "volume", "delays": 30},
        {"cause": "equipment", "delays": 15},
    ]


def test_only_three_leading_causes_returned(mock_execute_query):
    result = queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    causes = result["summary"][0]["leading_delay_causes"]

    assert len(causes) == 3


def test_null_delay_causes_are_excluded(monkeypatch):
    """A cause with a None value should not appear in the ranking."""
    calls = []

    def fake_execute_query(sql, params):
        calls.append(sql)

        if len(calls) == 1:
            return []

        return [{
            "airport": "JFK",
            "total_ops": 100,
            "total_delays": 20,
            "period_delays_per_100_ops": 20.0,
            "total_delay_minutes": 500,
            "weather_delays": None,
            "volume_delays": 10,
            "equipment_delays": 5,
            "runway_delays": None,
            "other_delays": 5,
        }]

    monkeypatch.setattr(
        queries,
        "execute_query",
        fake_execute_query,
    )

    result = queries.airport_operations(airports=["JFK"])

    causes = result["summary"][0]["leading_delay_causes"]

    assert all(
        cause["cause"] not in ["weather", "runway"]
        for cause in causes
    )

    assert len(causes) == 3


def test_daily_rows_preserve_airport_day_grain(mock_execute_query):
    result = queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    assert result["metadata"]["grain"] == "airport-day"

    notes = " ".join(result["interpretation_notes"]).lower()

    assert "airport-day" in notes
    assert "not hourly" in notes
    assert "do not duplicate" in notes


def test_no_hourly_expansion(mock_execute_query):
    queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    for call in mock_execute_query:
        sql = call["sql"].lower()

        assert "hour" not in sql
        assert "generate_series" not in sql
        assert "group by airport, date, hour" not in sql


def test_empty_results(monkeypatch):
    """Both queries returning no records should produce empty outputs."""
    monkeypatch.setattr(
        queries,
        "execute_query",
        lambda sql, params: [],
    )

    result = queries.airport_operations(
        airports=["JFK"],
        start_date="2026-04-01",
        end_date="2026-04-30",
    )

    assert result["summary"] == []
    assert result["daily_rows"] == []
    assert isinstance(result["metadata"], dict)


def test_invalid_date_range():
    with pytest.raises(ValueError):
        queries.airport_operations(
            airports=["JFK"],
            start_date="2026-05-01",
            end_date="2026-04-01",
        )


def test_interpretation_notes_distinguish_faa_from_bts(
    mock_execute_query,
):
    result = queries.airport_operations(airports=["JFK"])

    notes = " ".join(result["interpretation_notes"]).lower()

    assert "bts" in notes
    assert "distinct" in notes
