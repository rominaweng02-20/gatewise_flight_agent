# src/analytics/temporal_filters.py

from typing import Literal

DayType = Literal["all", "weekday", "weekend"]

DAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday"
)

WEEKDAYS = set(DAY_NAMES[:5])
WEEKENDS = set(DAY_NAMES[5:])
VALID_DAYS = set(DAY_NAMES)


def normalize_day_filters(
    day_type: str = "all",
    days_of_week: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Normalize and validate broad and specific day filters."""

    day_type = (day_type or "all").strip().lower()

    if day_type not in {"all", "weekday", "weekend"}:
        raise ValueError(
            "day_type must be 'all', 'weekday', or 'weekend'."
        )

    # Normalize capitalization and remove duplicates.
    normalized_days = []
    for day in days_of_week or []:
        day = day.strip().capitalize()

        if day not in VALID_DAYS:
            raise ValueError(f"Invalid day of week: {day}")

        if day not in normalized_days:
            normalized_days.append(day)

    selected_days = set(normalized_days)

    if day_type == "weekday" and not selected_days.issubset(WEEKDAYS):
        raise ValueError(
            "When day_type='weekday', days_of_week can only contain "
            "Monday through Friday."
        )

    if day_type == "weekend" and not selected_days.issubset(WEEKENDS):
        raise ValueError(
            "When day_type='weekend', days_of_week can only contain "
            "Saturday or Sunday."
        )

    return day_type, normalized_days


def validate_hour_filters(
    start_hour: int | None,
    end_hour: int | None,
) -> None:
    """Validate an optional start-inclusive, end-exclusive hour range."""

    if (start_hour is None) != (end_hour is None):
        raise ValueError(
            "Provide both start_hour and end_hour, or neither."
        )

    if start_hour is not None:
        if not (0 <= start_hour <= 23):
            raise ValueError("start_hour must be between 0 and 23.")

        if not (1 <= end_hour <= 24):
            raise ValueError("end_hour must be between 1 and 24.")

        if start_hour >= end_hour:
            raise ValueError("start_hour must be earlier than end_hour.")

ISODOW = {name: i for i, name in enumerate(DAY_NAMES, start=1)}

def temporal_sql(ts_expr, day_type="all", days_of_week=None, start_hour=None, end_hour=None):
    """Return (' AND ...' fragment, params). Assumes inputs passed the validators above.
    ts_expr is an Eastern-time timestamp column. Hours are start-inclusive, end-exclusive."""
    clauses, params = [], []
    if days_of_week:
        nums = ", ".join(str(n) for n in sorted(ISODOW[d] for d in days_of_week))
        clauses.append(f"EXTRACT(ISODOW FROM {ts_expr}) IN ({nums})")
    elif day_type == "weekday":
        clauses.append(f"EXTRACT(ISODOW FROM {ts_expr}) BETWEEN 1 AND 5")
    elif day_type == "weekend":
        clauses.append(f"EXTRACT(ISODOW FROM {ts_expr}) IN (6, 7)")
    if start_hour is not None:
        clauses.append(f"EXTRACT(HOUR FROM {ts_expr}) >= ? AND EXTRACT(HOUR FROM {ts_expr}) < ?")
        params += [start_hour, end_hour]
    return "".join(f" AND {c}" for c in clauses), params