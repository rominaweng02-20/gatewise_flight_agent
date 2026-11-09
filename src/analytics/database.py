from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = Path(
    os.getenv(
        "GATEWISE_DB_PATH",
        str(PROJECT_ROOT / "data" / "processed" / "gatewise.duckdb"),
    )
)

VALID_AIRPORTS = {"JFK", "EWR", "LGA"}

DEFAULT_START_DATE = "2026-04-01"
DEFAULT_END_DATE = "2026-08-31"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open the GateWise database in read-only mode."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"GateWise database not found at: {DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH), read_only=True)


def validate_airports(
    airports: Sequence[str] | None = None,
) -> list[str]:
    """Validate and normalize airport filters."""

    if airports is None:
        return sorted(VALID_AIRPORTS)

    normalized = [airport.upper().strip() for airport in airports]

    if not normalized:
        raise ValueError("At least one airport must be specified.")

    invalid = set(normalized) - VALID_AIRPORTS

    if invalid:
        raise ValueError(
            f"Unsupported airport(s): {sorted(invalid)}. "
            f"Valid airports are {sorted(VALID_AIRPORTS)}."
        )

    return sorted(set(normalized))


def validate_date_range(
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
) -> tuple[str, str]:
    """Validate ISO date strings and ensure chronological order."""

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Dates must use YYYY-MM-DD format."
        ) from exc

    if start > end:
        raise ValueError("start_date cannot be after end_date.")

    if start < date(2026, 4, 1) or end > date(2026, 8, 31):
        raise ValueError(
            "The primary analysis period is April 1 through "
            "August 31, 2026."
        )

    return start.isoformat(), end.isoformat()


def _serialize_value(value: Any) -> Any:
    """Convert DuckDB/Python values into JSON-compatible values."""

    if value is None:
        return None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (str, int, float, bool)):
        return value

    # Handles numeric scalar types returned by some query paths.
    if hasattr(value, "item"):
        return value.item()

    return str(value)


def execute_query(
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a parameterized read-only query and return JSON-safe rows."""

    con = get_connection()

    try:
        cursor = con.execute(sql, params or [])
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

        return [
            {
                column: _serialize_value(value)
                for column, value in zip(columns, row)
            }
            for row in rows
        ]
    finally:
        con.close()


def build_filter_sql(
    airports: Sequence[str],
    start_date: str,
    end_date: str,
    date_column: str = "date",
) -> tuple[str, list[Any]]:
    """
    Build a parameterized airport/date filter.

    date_column must be an internally defined SQL identifier,
    never a value supplied directly by the user.
    """

    placeholders = ", ".join(["?"] * len(airports))

    sql = f"""
        airport IN ({placeholders})
        AND {date_column} BETWEEN CAST(? AS DATE)
                              AND CAST(? AS DATE)
    """

    params = [*airports, start_date, end_date]

    return sql, params