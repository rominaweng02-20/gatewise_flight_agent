from __future__ import annotations

from typing import Sequence

from src.analytics.database import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    build_filter_sql,
    execute_query,
    validate_airports,
    validate_date_range,
)
from src.analytics.temporal_filters import (
    normalize_day_filters,
    validate_hour_filters,
    temporal_sql,
)


def _metadata(
    source: str,
    grain: str,
    airports: list[str],
    start_date: str,
    end_date: str,
    description: str,
) -> dict:
    return {
        "source": source,
        "grain": grain,
        "airports": airports,
        "date_range": {
            "start": start_date,
            "end": end_date,
        },
        "description": description,
    }


def _validate_inputs(
    airports: Sequence[str] | None,
    start_date: str,
    end_date: str,
) -> tuple[list[str], str, str]:
    airport_list = validate_airports(airports)
    start, end = validate_date_range(start_date, end_date)

    return airport_list, start, end


def airport_overview(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
) -> dict:
    """
    Compare airport-level flight, security, weather, and FAA metrics.

    Daily rates are reported as averages of the daily rates.
    The FAA period-wide rate is separately calculated from total counts.
    """

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    filter_sql, params = build_filter_sql(
        airport_list, start, end
    )

    sql = f"""
        SELECT
            airport,
            COUNT(*) AS calendar_days,

            SUM(scheduled_flights) AS scheduled_flights,
            SUM(cancellations) AS cancellations,
            SUM(departed_flights) AS departed_flights,

            AVG(cancellation_rate) AS avg_daily_cancellation_rate,
            AVG(departure_15min_late_rate)
                AS avg_daily_15min_late_rate,

            AVG(mean_departure_delay_min)
                AS avg_daily_mean_departure_delay_min,

            SUM(flights_15min_late) AS flights_15min_late,

            CASE
                WHEN SUM(departed_flights) > 0
                THEN 100.0 * SUM(cancellations)
                     / SUM(scheduled_flights)
                ELSE NULL
            END AS period_cancellation_rate_pct,

            CASE
                WHEN SUM(scheduled_flights) > 0
                THEN SUM(weighted_avg_wait_min * security_samples)
                        / NULLIF(SUM(security_samples), 0)
                ELSE NULL
            END AS sample_weighted_security_wait_min,

            SUM(security_samples) AS security_samples,
            SUM(security_observed_hours)
                AS security_observed_hours,

            AVG(avg_temperature_c) AS avg_temperature_c,
            AVG(min_visibility_km) AS avg_daily_min_visibility_km,
            MAX(max_wind_gust_m_s) AS max_wind_gust_m_s,
            SUM(reported_precipitation_mm)
                AS reported_precipitation_mm,

            SUM(total_ops) AS faa_total_operations,
            SUM(total_delays) AS faa_total_delays,

            CASE
                WHEN SUM(total_ops) > 0
                THEN 100.0 * SUM(total_delays) / SUM(total_ops)
                ELSE NULL
            END AS faa_delays_per_100_ops,

            AVG(delays_per_100_ops)
                AS avg_daily_faa_delays_per_100_ops

        FROM airport_daily_panel
        WHERE {filter_sql}
        GROUP BY airport
        ORDER BY airport
    """

    rows = execute_query(sql, params)

    return {
        "metadata": _metadata(
            "airport_daily_panel",
            "airport-day",
            airport_list,
            start,
            end,
            (
                "Cross-domain airport comparison. Daily flight and FAA "
                "rates are distinguished from period-wide count-based "
                "rates. Security wait is weighted by reported samples."
            ),
        ),
        "rows": rows,
        "interpretation_notes": [
            "The average daily 15-minute-late rate is not necessarily "
            "the same as the period-wide flight delay rate.",
            "FAA delays per 100 operations is calculated from summed "
            "FAA delay and operation counts.",
            "Security wait is sample-weighted; it is not an average "
            "of terminal percentiles.",
            "Weather summaries use available observations and may "
            "have missing hours.",
            "These metrics describe separate operational processes "
            "and do not establish that security waits cause flight delays."
        ],
    }

def flight_reliability(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    grain: str = "daily",
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: str = "all",
    days_of_week: Sequence[str] | None = None,
) -> dict:
    """
    Analyze flight departure reliability at daily, hourly, or monthly grain.

    Hour filters apply only to hourly grain and use scheduled departure hour.
    Weekday filters use the scheduled departure's airport-local date/time.
    """

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    # Validate grain
    if grain not in {"daily", "hourly", "monthly"}:
        raise ValueError(
            "grain must be 'daily', 'hourly', or 'monthly'."
        )

    # Validate day type
    day_type = day_type.lower().strip()

    if day_type not in {"all", "weekday", "weekend"}:
        raise ValueError(
            "day_type must be all, weekday, or weekend."
        )

    # Map weekdays to ISO weekday numbers
    valid_days = {
        "monday": 1,
        "tuesday": 2,
        "wednesday": 3,
        "thursday": 4,
        "friday": 5,
        "saturday": 6,
        "sunday": 7,
    }

    # Normalize weekday inputs
    normalized_days = [
        day.strip().lower()
        for day in (days_of_week or [])
    ]

    if any(day not in valid_days for day in normalized_days):
        raise ValueError(
            "days_of_week must contain valid weekday names."
        )

    if len(normalized_days) != len(set(normalized_days)):
        raise ValueError(
            "days_of_week cannot contain duplicates."
        )

    selected_day_numbers = [
        valid_days[day] for day in normalized_days
    ]

    selected_days = [
        day.capitalize() for day in normalized_days
    ]

    # Validate day_type compatibility
    weekday_set = {
        "monday", "tuesday", "wednesday",
        "thursday", "friday"
    }
    weekend_set = {"saturday", "sunday"}

    if (
        day_type == "weekday"
        and not set(normalized_days).issubset(weekday_set)
    ):
        raise ValueError(
            "days_of_week must contain weekdays when day_type='weekday'."
        )

    if (
        day_type == "weekend"
        and not set(normalized_days).issubset(weekend_set)
    ):
        raise ValueError(
            "days_of_week must contain weekends when day_type='weekend'."
        )

    # Validate hour filters
    if start_hour is not None and not 0 <= start_hour <= 23:
        raise ValueError("start_hour must be between 0 and 23.")

    if end_hour is not None and not 1 <= end_hour <= 24:
        raise ValueError("end_hour must be between 1 and 24.")

    if (
        start_hour is not None
        and end_hour is not None
        and start_hour >= end_hour
    ):
        raise ValueError(
            "start_hour must be earlier than end_hour."
        )

    # Hour filters require hourly data
    if grain != "hourly" and (
        start_hour is not None or end_hour is not None
    ):
        raise ValueError(
            "start_hour and end_hour can only be used with grain='hourly'."
        )

    # Select table and aggregation based on grain
    if grain == "monthly":
        table = "flight_daily"
        date_column = "date"

        select_columns = """
            DATE_TRUNC('month', date)::DATE AS date,
            NULL::INTEGER AS scheduled_departure_hour,
            SUM(scheduled_flights) AS scheduled_flights,
            SUM(cancellations) AS cancellations,
            SUM(departed_flights) AS departed_flights,
            SUM(delay_observations) AS delay_observations,
            SUM(classified_departed_flights) AS classified_departed_flights,
            SUM(flights_15min_late) AS flights_15min_late,

            SUM(mean_departure_delay_min * delay_observations)
                / NULLIF(SUM(delay_observations), 0)
                AS mean_departure_delay_min,

            SUM(cancellations) * 1.0
                / NULLIF(SUM(scheduled_flights), 0)
                AS cancellation_rate,

            SUM(flights_15min_late) * 1.0
                / NULLIF(SUM(classified_departed_flights), 0)
                AS departure_15min_late_rate
        """

        group_by = "airport, DATE_TRUNC('month', date)"
        order_by = "airport, date"
        output_grain = "airport-month"
        day_column = "date"

    elif grain == "daily":
        table = "flight_daily"
        date_column = "date"

        select_columns = """
            date,
            scheduled_flights,
            cancellations,
            departed_flights,
            delay_observations,
            classified_departed_flights,
            flights_15min_late,
            mean_departure_delay_min,
            cancellation_rate,
            departure_15min_late_rate
        """

        group_by = None
        order_by = "airport, date"
        output_grain = "airport-day"
        day_column = "date"

    else:
        table = "flight_hourly"
        date_column = "date"

        select_columns = """
            date,
            scheduled_departure_hour,
            hour_et,
            scheduled_flights,
            cancellations,
            departed_flights,
            delay_observations,
            classified_departed_flights,
            flights_15min_late,
            mean_departure_delay_min,
            cancellation_rate,
            departure_15min_late_rate
        """

        group_by = None
        order_by = "airport, date, scheduled_departure_hour"
        output_grain = "airport-scheduled-hour"
        day_column = "hour_et"

    # Build airport and date filters
    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column=date_column,
    )

    additional_filters = []

    # Start-inclusive scheduled departure hour
    if start_hour is not None:
        additional_filters.append(
            "scheduled_departure_hour >= ?"
        )
        params.append(start_hour)

    # End-exclusive scheduled departure hour
    if end_hour is not None:
        additional_filters.append(
            "scheduled_departure_hour < ?"
        )
        params.append(end_hour)

    # Broad weekday/weekend filter
    if day_type == "weekday":
        additional_filters.append(
            f"EXTRACT(ISODOW FROM {day_column}) BETWEEN 1 AND 5"
        )

    elif day_type == "weekend":
        additional_filters.append(
            f"EXTRACT(ISODOW FROM {day_column}) IN (6, 7)"
        )

    # Specific weekday filter
    if selected_day_numbers:
        placeholders = ", ".join(
            "?" for _ in selected_day_numbers
        )

        additional_filters.append(
            f"EXTRACT(ISODOW FROM {day_column}) IN ({placeholders})"
        )

        params.extend(selected_day_numbers)

    extra_sql = (
        " AND " + " AND ".join(additional_filters)
        if additional_filters
        else ""
    )

    grouping_sql = (
        f"GROUP BY {group_by}" if group_by else ""
    )

    sql = f"""
        SELECT
            airport,
            {select_columns}
        FROM {table}
        WHERE {filter_sql}{extra_sql}
        {grouping_sql}
        ORDER BY {order_by}
    """

    rows = execute_query(sql, params)

    return {
        "metadata": _metadata(
            table,
            output_grain,
            airport_list,
            start,
            end,
            (
                "Monthly mean departure delay is weighted by the number "
                "of valid delay observations. Cancellation and 15-minute-late "
                "rates are calculated from summed counts and their respective "
                "denominators. Hourly records use scheduled departure hour."
            ),
        ),
        "filters": {
            "grain": grain,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "day_type": day_type,
            "days_of_week": selected_days,
        },
        "rows": rows,
        "interpretation_notes": [
            "Cancellation rate uses scheduled flights as its denominator.",
            "Departure 15-minute-late rate uses classified departed flights.",
            "Do not infer a 30-minute-late rate from the 15-minute-late rate.",
            "Mean departure delay is weighted by valid delay observations.",
            "Monthly mean departure delay is not calculated by averaging daily means.",
            "Hourly records use scheduled departure hour, not actual departure hour.",
            "Hour filters are start-inclusive and end-exclusive.",
            "Weekday filters use the scheduled departure's airport-local date.",
            "Missing hourly records are not interpreted as zero-delay observations.",
        ],
    }

def flight_risk_profile(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: str = "all",
    days_of_week: Sequence[str] | None = None,
) -> dict:
    """Pooled departure risk for a day/hour slot. Hours are scheduled departure hour (Eastern),
    start-inclusive and end-exclusive."""

    airport_list, start, end = _validate_inputs(airports, start_date, end_date)
    day_type, days_of_week = normalize_day_filters(day_type, list(days_of_week or []))
    validate_hour_filters(start_hour, end_hour)

    filter_sql, params = build_filter_sql(airport_list, start, end, date_column="date")
    extra_sql, extra_params = temporal_sql("hour_et", day_type, days_of_week, start_hour, end_hour)

    sql = f"""
        SELECT
            airport,
            SUM(scheduled_flights) AS scheduled_flights,
            SUM(classified_departed_flights) AS classified_departed_flights,
            SUM(flights_15min_late) AS flights_15min_late,
            SUM(flights_15min_late) * 1.0
                / NULLIF(SUM(classified_departed_flights), 0) AS departure_15min_late_rate,
            SUM(cancellations) * 1.0
                / NULLIF(SUM(scheduled_flights), 0) AS cancellation_rate,
            SUM(mean_departure_delay_min * delay_observations)
                / NULLIF(SUM(delay_observations), 0) AS mean_departure_delay_min,
            COUNT(*) AS observed_hours,
            COUNT(DISTINCT date) AS observed_days
        FROM flight_hourly
        WHERE {filter_sql}{extra_sql}
        GROUP BY airport
        ORDER BY airport
    """
    summary = execute_query(sql, [*params, *extra_params])

    return {
        "metadata": _metadata(
            "flight_hourly", "airport-scheduled-hour (summarized)", airport_list, start, end,
            "Pooled departure risk for the filtered slot. Rates come from summed counts.",
        ),
        "filters": {"start_hour": start_hour, "end_hour": end_hour,
                    "day_type": day_type, "days_of_week": days_of_week},
        "summary": summary,
        "interpretation_notes": [
            "Historical risk for this slot, not a forecast for a specific flight.",
            "Late rate uses classified departed flights; cancellation rate uses scheduled flights.",
            "Only a 15-minute-late rate exists. Do not infer a 30-minute rate.",
            "Hours are scheduled departure hour, Eastern, start-inclusive and end-exclusive.",
            "Pooled across airlines; airline-specific effects are not in the data.",
        ],
    }


def security_patterns(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    grain: str = "daily",
    terminal: str | None = None,
    queue_type: str | None = None,
) -> dict:
    """Analyze airport security wait patterns, with optional terminal and queue filters."""

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    if grain not in {"daily", "hourly"}:
        raise ValueError("grain must be 'daily' or 'hourly'.")

    if queue_type is not None:
        queue_type = queue_type.strip().lower()
        if queue_type not in {"standard", "precheck"}:
            raise ValueError(
                "queue_type must be 'standard' or 'precheck'."
            )

    # ---------------------------------------------------------
    # PATH 1: Existing airport-wide queries (no terminal filters)
    # ---------------------------------------------------------
    if terminal is None and queue_type is None:

        if grain == "daily":
            table = "security_airport_daily"
            date_column = "date"
            order_column = "date"

            select_columns = """
                date,
                weighted_avg_wait_min,
                total_samples,
                observed_hours,
                terminal_count
            """

        else:
            table = "security_airport_hourly"
            date_column = "CAST(hour_et AS DATE)"
            order_column = "hour_et"

            select_columns = """
                hour_et,
                weighted_avg_wait_min,
                standard_weighted_avg_wait_min,
                precheck_weighted_avg_wait_min,
                total_samples,
                terminal_count,
                terminal_queue_records
            """

        filter_sql, params = build_filter_sql(
            airport_list,
            start,
            end,
            date_column=date_column,
        )

        sql = f"""
            SELECT
                airport,
                {select_columns}
            FROM {table}
            WHERE {filter_sql}
            ORDER BY airport, {order_column}
        """

        rows = execute_query(sql, params)

        return {
            "metadata": _metadata(
                table,
                "airport-day" if grain == "daily" else "airport-hour",
                airport_list,
                start,
                end,
                (
                    "Security wait estimates aggregated using sample counts. "
                    "Standard and PreCheck waits are available at hourly grain."
                ),
            ),
            "rows": rows,
            "interpretation_notes": [
                "Wait estimates are based on reported security samples.",
                "Missing security records are not zero-minute waits.",
                "Terminal-level percentile values should not be averaged "
                "to produce airport-wide percentiles.",
                "Daily airport-level data does not contain separate "
                "standard and PreCheck estimates.",
                "A missing hour or day indicates absent observations, "
                "not necessarily that the airport had no queue."
            ],
        }

    # ---------------------------------------------------------
    # PATH 2: Terminal- and/or queue-specific queries
    # ---------------------------------------------------------
    table = "security_waits_hourly"

    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column="CAST(hour_et AS DATE)",
    )

    params = list(params)

    if terminal is not None:
        filter_sql += """
            AND LOWER(TRIM(terminal)) = LOWER(TRIM(?))
        """
        params.append(terminal.strip())

    if queue_type is not None:
        filter_sql += """
            AND LOWER(TRIM(queue_type)) = ?
        """
        params.append(queue_type)

    if grain == "hourly":
        select_columns = """
            airport,
            terminal,
            queue_type,
            hour_et,
            avg_wait,
            p50_wait,
            p75_wait,
            p95_wait,
            max_wait,
            n_samples
        """

        sql = f"""
            SELECT
                {select_columns}
            FROM {table}
            WHERE {filter_sql}
            ORDER BY airport, terminal, queue_type, hour_et
        """

        metadata_grain = "terminal-queue-hour"

    else:
        sql = f"""
            SELECT
                airport,
                terminal,
                queue_type,
                CAST(hour_et AS DATE) AS date,
                SUM(avg_wait * n_samples)
                    / NULLIF(SUM(n_samples), 0)
                    AS weighted_avg_wait_min,
                SUM(n_samples) AS total_samples,
                COUNT(DISTINCT hour_et) AS observed_hours
            FROM {table}
            WHERE {filter_sql}
            GROUP BY
                airport,
                terminal,
                queue_type,
                CAST(hour_et AS DATE)
            ORDER BY
                airport,
                terminal,
                queue_type,
                date
        """

        metadata_grain = "terminal-queue-day"

    rows = execute_query(sql, params)

    return {
        "metadata": _metadata(
            table,
            metadata_grain,
            airport_list,
            start,
            end,
            (
                "Terminal- and queue-specific security estimates. "
                "Daily averages are weighted by the number of samples."
            ),
        ),
        "rows": rows,
        "interpretation_notes": [
            "Wait estimates are based on reported security samples.",
            "Missing security records are not zero-minute waits.",
            "Hourly percentile estimates describe the reported "
            "distribution for that terminal and queue.",
            "Daily percentiles are not provided because hourly "
            "percentiles cannot be averaged to calculate daily percentiles.",
            "Daily averages are weighted by sample counts.",
            "A missing hour or day indicates absent observations, "
            "not necessarily that the terminal had no queue.",
            "Results are specific to the selected terminal and queue "
            "when those filters are supplied."
        ],
    }



def security_arrival_profile(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: str = "all",
    days_of_week: Sequence[str] | None = None,
    queue_type: str = "standard",
) -> dict:
    """
    Summarize the distribution of observed hourly airport security estimates.

    Hours are Eastern, start-inclusive and end-exclusive.
    Percentiles describe hourly airport-level estimates,
    not individual passenger wait times.
    """

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    # Validate day type
    day_type = day_type.lower().strip()

    if day_type not in {"all", "weekday", "weekend"}:
        raise ValueError(
            "day_type must be all, weekday, or weekend."
        )

    # Map weekdays to ISO weekday numbers
    valid_days = {
        "monday": 1,
        "tuesday": 2,
        "wednesday": 3,
        "thursday": 4,
        "friday": 5,
        "saturday": 6,
        "sunday": 7,
    }

    # Normalize input for validation and SQL filtering
    normalized_days = [
        day.strip().lower()
        for day in (days_of_week or [])
    ]

    # Validate weekday names
    if any(day not in valid_days for day in normalized_days):
        raise ValueError(
            "days_of_week must contain valid weekday names."
        )

    # Reject duplicates
    if len(normalized_days) != len(set(normalized_days)):
        raise ValueError(
            "days_of_week cannot contain duplicates."
        )

    # Convert weekdays to ISO numbers for SQL
    selected_day_numbers = [
        valid_days[day] for day in normalized_days
    ]

    # Preserve readable capitalization in returned metadata
    selected_days = [
        day.capitalize() for day in normalized_days
    ]

    # Make sure specific days are compatible with day_type
    weekday_set = {
        "monday", "tuesday", "wednesday",
        "thursday", "friday"
    }
    weekend_set = {"saturday", "sunday"}

    if (
        day_type == "weekday"
        and not set(normalized_days).issubset(weekday_set)
    ):
        raise ValueError(
            "days_of_week must contain weekdays when day_type='weekday'."
        )

    if (
        day_type == "weekend"
        and not set(normalized_days).issubset(weekend_set)
    ):
        raise ValueError(
            "days_of_week must contain weekends when day_type='weekend'."
        )

    # Validate hour filters
    if start_hour is not None and not 0 <= start_hour <= 23:
        raise ValueError("start_hour must be between 0 and 23.")

    if end_hour is not None and not 1 <= end_hour <= 24:
        raise ValueError("end_hour must be between 1 and 24.")

    if (
        start_hour is not None
        and end_hour is not None
        and start_hour >= end_hour
    ):
        raise ValueError(
            "start_hour must be earlier than end_hour."
        )

    # Select security wait column using a fixed whitelist
    queue_columns = {
        "overall": "weighted_avg_wait_min",
        "standard": "standard_weighted_avg_wait_min",
        "precheck": "precheck_weighted_avg_wait_min",
    }

    if queue_type not in queue_columns:
        raise ValueError(
            "queue_type must be overall, standard, or precheck."
        )

    wait_column = queue_columns[queue_type]

    # Build date and airport filters
    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column="CAST(hour_et AS DATE)",
    )

    additional_filters = []

    # Start-inclusive hour filter
    if start_hour is not None:
        additional_filters.append(
            "EXTRACT(HOUR FROM hour_et) >= ?"
        )
        params.append(start_hour)

    # End-exclusive hour filter
    if end_hour is not None:
        additional_filters.append(
            "EXTRACT(HOUR FROM hour_et) < ?"
        )
        params.append(end_hour)

    # Broad weekday/weekend filter
    if day_type == "weekday":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5"
        )
    elif day_type == "weekend":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) IN (6, 7)"
        )

    # Specific weekday filter
    if selected_day_numbers:
        placeholders = ", ".join(
            "?" for _ in selected_day_numbers
        )

        additional_filters.append(
            f"EXTRACT(ISODOW FROM hour_et) IN ({placeholders})"
        )

        params.extend(selected_day_numbers)

    extra_sql = (
        " AND " + " AND ".join(additional_filters)
        if additional_filters
        else ""
    )

    sql = f"""
        SELECT
            airport,
            ? AS queue_type,
            MIN(CAST(hour_et AS DATE)) AS observed_start_date,
            MAX(CAST(hour_et AS DATE)) AS observed_end_date,

            QUANTILE_CONT({wait_column}, 0.50) AS p50_wait_min,
            QUANTILE_CONT({wait_column}, 0.90) AS p90_wait_min,
            AVG({wait_column}) AS mean_wait_min,
            STDDEV_SAMP({wait_column}) AS stddev_wait_min,

            COUNT({wait_column}) AS observed_hours,
            COUNT(DISTINCT CAST(hour_et AS DATE)) AS observed_days

        FROM security_airport_hourly
        WHERE {filter_sql}{extra_sql}
          AND {wait_column} IS NOT NULL
        GROUP BY airport
        ORDER BY airport
    """

    # queue_type placeholder comes before all WHERE parameters
    rows = execute_query(sql, [queue_type, *params])

    return {
        "metadata": _metadata(
            "security_airport_hourly",
            "airport-hour",
            airport_list,
            start,
            end,
            (
                "Distribution of observed hourly airport-level "
                "weighted security wait estimates. Percentiles are "
                "not passenger-level wait-time percentiles."
            ),
        ),
        "filters": {
            "start_hour": start_hour,
            "end_hour": end_hour,
            "day_type": day_type,
            "days_of_week": selected_days,
            "queue_type": queue_type,
        },
        "summary": rows,
        "interpretation_notes": [
            "P50 and P90 describe the distribution of observed hourly "
            "airport-level estimates, not individual passenger waits.",
            "Hours are Eastern, start-inclusive and end-exclusive.",
            "Missing hourly estimates are excluded, not treated as zero.",
            "Daily security records cannot reconstruct these percentiles.",
            "Standard and PreCheck estimates are available only at hourly grain.",
            "An empty summary means no matching observations were available.",
        ],
    }

    
def weather_conditions(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    grain: str = "daily",
) -> dict:
    """Analyze airport weather conditions at daily or hourly grain."""

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    if grain not in {"daily", "hourly"}:
        raise ValueError("grain must be 'daily' or 'hourly'.")

    if grain == "daily":
        table = "weather_airport_daily"
        date_column = "date"

        select_columns = """
            date,
            avg_temperature_c,
            min_visibility_km,
            avg_visibility_km,
            max_wind_speed_m_s,
            max_wind_gust_m_s,
            reported_precipitation_mm,
            weather_hours,
            precipitation_report_hours,
            precipitation_trace_hours
        """

        order_column = "date"

    else:
        table = "weather_hourly_local"
        date_column = "CAST(hour_et AS DATE)"

        select_columns = """
            hour_et,
            temperature_c,
            precipitation_mm,
            precipitation_trace,
            visibility_km,
            wind_speed_m_s,
            wind_gust_m_s,
            weather_report_count,
            present_weather
        """

        order_column = "hour_et"

    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column=date_column,
    )

    sql = f"""
        SELECT
            airport,
            {select_columns}
        FROM {table}
        WHERE {filter_sql}
        ORDER BY airport, {order_column}
    """

    rows = execute_query(sql, params)

    return {
        "metadata": _metadata(
            table,
            "airport-day" if grain == "daily" else "airport-hour",
            airport_list,
            start,
            end,
            (
                "NOAA weather observations summarized at the requested "
                "grain. Hourly timestamps use local Eastern time."
            ),
        ),
        "rows": rows,
        "interpretation_notes": [
            "Temperature is in degrees Celsius.",
            "Visibility is in kilometers.",
            "Wind speed and gusts are in meters per second.",
            "Precipitation is in millimeters.",
            "A precipitation trace is distinct from a measured "
            "positive precipitation amount.",
            "Missing weather values are not interpreted as favorable "
            "weather or zero precipitation."
        ],
    }
def weather_risk_profile(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    visibility_threshold_km: float = 5.0,
    precipitation_threshold_mm: float = 1.0,
    wind_threshold_m_s: float = 10.0,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: str = "all",
    days_of_week: Sequence[str] | None = None,
) -> dict:
    """
    Summarize hourly weather conditions using explicit configurable thresholds.

    Temporal filters use hour_et, which represents local Eastern time.
    Hour filters are start-inclusive and end-exclusive.
    Percentages use valid observations for the corresponding variable.
    """

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    # Validate and normalize temporal filters using shared helpers.
    day_type, days_of_week = normalize_day_filters(
        day_type,
        list(days_of_week or [])
    )

    validate_hour_filters(start_hour, end_hour)

    # Validate weather thresholds.
    if visibility_threshold_km <= 0:
        raise ValueError("Visibility threshold must be positive.")

    if precipitation_threshold_mm < 0:
        raise ValueError("Precipitation threshold cannot be negative.")

    if wind_threshold_m_s <= 0:
        raise ValueError("Wind threshold must be positive.")

    # Build airport and date filters.
    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column="CAST(hour_et AS DATE)",
    )

    # Map weekdays to ISO weekday numbers:
    # Monday = 1, ..., Sunday = 7.
    valid_days = {
        "monday": 1,
        "tuesday": 2,
        "wednesday": 3,
        "thursday": 4,
        "friday": 5,
        "saturday": 6,
        "sunday": 7,
    }

    normalized_days = [
        day.strip().lower()
        for day in days_of_week
    ]

    selected_day_numbers = [
        valid_days[day]
        for day in normalized_days
    ]

    selected_days = [
        day.capitalize()
        for day in normalized_days
    ]

    # Build temporal SQL filters.
    additional_filters = []
    temporal_params = []

    # Start-inclusive hour filter.
    if start_hour is not None:
        additional_filters.append(
            "EXTRACT(HOUR FROM hour_et) >= ?"
        )
        temporal_params.append(start_hour)

    # End-exclusive hour filter.
    if end_hour is not None:
        additional_filters.append(
            "EXTRACT(HOUR FROM hour_et) < ?"
        )
        temporal_params.append(end_hour)

    # Broad weekday/weekend filter.
    if day_type == "weekday":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5"
        )

    elif day_type == "weekend":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) IN (6, 7)"
        )

    # Specific weekday filter.
    if selected_day_numbers:
        placeholders = ", ".join(
            "?" for _ in selected_day_numbers
        )

        additional_filters.append(
            f"EXTRACT(ISODOW FROM hour_et) IN ({placeholders})"
        )

        temporal_params.extend(selected_day_numbers)

    # Combine date, airport, and temporal filters.
    extra_sql = (
        " AND " + " AND ".join(additional_filters)
        if additional_filters
        else ""
    )

    combined_filter_sql = filter_sql + extra_sql
    combined_params = [*params, *temporal_params]

    # --------------------------------------------------
    # Summary query
    # --------------------------------------------------

    summary_sql = f"""
        SELECT
            airport,

            COUNT(*) AS total_hourly_rows,

            COUNT(visibility_km)
                AS valid_visibility_observations,

            COUNT(*) FILTER (
                WHERE visibility_km < ?
            ) AS low_visibility_observations,

            100.0 * COUNT(*) FILTER (
                WHERE visibility_km < ?
            ) / NULLIF(COUNT(visibility_km), 0)
                AS low_visibility_pct,

            COUNT(precipitation_mm)
                AS valid_precipitation_observations,

            COUNT(*) FILTER (
                WHERE precipitation_mm >= ?
            ) AS significant_precipitation_observations,

            100.0 * COUNT(*) FILTER (
                WHERE precipitation_mm >= ?
            ) / NULLIF(COUNT(precipitation_mm), 0)
                AS significant_precipitation_pct,

            COUNT(wind_speed_m_s)
                AS valid_wind_observations,

            COUNT(*) FILTER (
                WHERE wind_speed_m_s >= ?
            ) AS high_wind_observations,

            100.0 * COUNT(*) FILTER (
                WHERE wind_speed_m_s >= ?
            ) / NULLIF(COUNT(wind_speed_m_s), 0)
                AS high_wind_pct,

            AVG(visibility_km) AS mean_visibility_km,
            MAX(wind_gust_m_s) AS max_wind_gust_m_s

        FROM weather_hourly_local
        WHERE {combined_filter_sql}
        GROUP BY airport
        ORDER BY airport
    """

    summary_params = [
        visibility_threshold_km,
        visibility_threshold_km,
        precipitation_threshold_mm,
        precipitation_threshold_mm,
        wind_threshold_m_s,
        wind_threshold_m_s,
        *combined_params,
    ]

    summary = execute_query(summary_sql, summary_params)

    # --------------------------------------------------
    # Hourly observation coverage query
    # --------------------------------------------------

    coverage_sql = f"""
        SELECT
            airport,
            EXTRACT(HOUR FROM hour_et) AS departure_hour,

            COUNT(*) AS observed_hours,

            COUNT(visibility_km)
                AS visibility_observations,

            COUNT(precipitation_mm)
                AS precipitation_observations,

            COUNT(wind_speed_m_s)
                AS wind_observations

        FROM weather_hourly_local
        WHERE {combined_filter_sql}
        GROUP BY airport, departure_hour
        ORDER BY airport, departure_hour
    """

    coverage = execute_query(coverage_sql, combined_params)

    # --------------------------------------------------
    # Return results and metadata
    # --------------------------------------------------

    return {
        "metadata": _metadata(
            "weather_hourly_local",
            "airport-hour",
            airport_list,
            start,
            end,
            "Hourly weather risk indicators and observation coverage.",
        ),

        "filters": {
            "start_hour": start_hour,
            "end_hour": end_hour,
            "day_type": day_type,
            "days_of_week": selected_days,
        },

        "thresholds": {
            "visibility_below_km": visibility_threshold_km,
            "precipitation_at_least_mm": precipitation_threshold_mm,
            "wind_speed_at_least_m_s": wind_threshold_m_s,
        },

        "summary": summary,
        "hourly_coverage": coverage,

        "interpretation_notes": [
            "Each percentage uses valid observations for that weather variable.",
            "Missing observations are excluded from the corresponding denominator.",
            "Precipitation traces are not counted as measured precipitation amounts.",
            "These thresholds are analytical categories, not official aviation safety thresholds.",
            "Weather conditions coinciding with delays do not establish causation.",
            "Temporal filters use local Eastern time.",
            "Hour filters are start-inclusive and end-exclusive.",
        ],
    }

def airport_operations(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
) -> dict:
    """Analyze FAA OPSNET airport-day operations and delay causes."""

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    filter_sql, params = build_filter_sql(
        airport_list, start, end
    )

    sql = f"""
        SELECT
            airport,
            date,
            total_ops,
            total_delays,
            100.0 * total_delays / NULLIF(total_ops, 0)
                AS delays_per_100_ops,
            avg_delay_minutes,
            total_delay_minutes,
            cause_weather,
            cause_volume,
            cause_equipment,
            cause_runway,
            cause_other,
            tmi_to_delays,
            occurred_dep_delays,
            occurred_abrn_delays,
            tmi_from_local_delays,
            tmi_from_nonlocal_delays
        FROM faa_operations_daily
        WHERE {filter_sql}
        ORDER BY airport, date
    """

    rows = execute_query(sql, params)

    summary_sql = f"""
        SELECT
            airport,
            SUM(total_ops) AS total_ops,
            SUM(total_delays) AS total_delays,
            100.0 * SUM(total_delays)
                / NULLIF(SUM(total_ops), 0)
                AS period_delays_per_100_ops,
            SUM(total_delay_minutes) AS total_delay_minutes,
            SUM(cause_weather) AS weather_delays,
            SUM(cause_volume) AS volume_delays,
            SUM(cause_equipment) AS equipment_delays,
            SUM(cause_runway) AS runway_delays,
            SUM(cause_other) AS other_delays
        FROM faa_operations_daily
        WHERE {filter_sql}
        GROUP BY airport
        ORDER BY airport
    """

    summary = execute_query(summary_sql, params)
    cause_columns = {
        "weather": "weather_delays",
        "volume": "volume_delays",
        "equipment": "equipment_delays",
        "runway": "runway_delays",
        "other": "other_delays",
    }

    for airport_summary in summary:
        causes = [
            {
                "cause": cause,
                "delays": airport_summary[column],
            }
            for cause, column in cause_columns.items()
            if airport_summary[column] is not None
        ]

        airport_summary["leading_delay_causes"] = sorted(
            causes,
            key=lambda item: item["delays"],
            reverse=True,
        )[:3]
    return {
        "metadata": _metadata(
            "faa_operations_daily",
            "airport-day",
            airport_list,
            start,
            end,
            (
                "FAA OPSNET operational delay counts and causes. "
                "Period-wide delay rates are calculated from summed "
                "delays divided by summed operations."
            ),
        ),
        "summary": summary,
        "daily_rows": rows,
        "interpretation_notes": [
            "FAA records are airport-day observations, not hourly records.",
            "Period-wide delays per 100 operations is count-weighted.",
            "FAA operational delay counts are distinct from BTS "
            "flight-level departure delay metrics.",
            "Do not duplicate daily FAA values across hours."
        ],
    }


def hourly_airport_patterns(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: str = "all",
    queue_type: str = "standard",
) -> dict:
    """
    Explore hourly co-occurrence of security, weather, and flight metrics.

    This is descriptive association, not a causal analysis.
    """

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    filter_sql, params = build_filter_sql(
    airport_list,
    start,
    end,
    date_column="CAST(hour_et AS DATE)",
    )

    if start_hour is not None and not 0 <= start_hour <= 23:
        raise ValueError("start_hour must be between 0 and 23.")

    if end_hour is not None and not 0 <= end_hour <= 23:
        raise ValueError("end_hour must be between 0 and 23.")

    if (
        start_hour is not None
        and end_hour is not None
        and start_hour > end_hour
    ):
        raise ValueError("start_hour cannot be after end_hour.")

    if day_type not in {"all", "weekday", "weekend"}:
        raise ValueError("day_type must be all, weekday, or weekend.")

    queue_columns = {
        "overall": "weighted_avg_wait_min",
        "standard": "standard_weighted_avg_wait_min",
        "precheck": "precheck_weighted_avg_wait_min",
    }

    if queue_type not in queue_columns:
        raise ValueError("Invalid queue_type.")

    security_column = queue_columns[queue_type]

    additional_filters = []

    if start_hour is not None:
        additional_filters.append("hour_of_day >= ?")
        params.append(start_hour)

    if end_hour is not None:
        additional_filters.append("hour_of_day <= ?")
        params.append(end_hour)

    if day_type == "weekday":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) BETWEEN 1 AND 5"
        )
    elif day_type == "weekend":
        additional_filters.append(
            "EXTRACT(ISODOW FROM hour_et) IN (6, 7)"
        )

    extra_sql = (
        " AND " + " AND ".join(additional_filters)
        if additional_filters
        else ""
    )

    sql = f"""
        SELECT
            airport,

            COUNT(*) AS airport_hour_rows,

            AVG({security_column}) AS mean_security_wait_min,
            QUANTILE_CONT({security_column}, 0.50)
                AS p50_hourly_security_wait_min,
            QUANTILE_CONT({security_column}, 0.90)
                AS p90_hourly_security_wait_min,
            COUNT({security_column}) AS security_observed_hours,

            AVG(visibility_km) AS mean_visibility_km,
            COUNT(visibility_km) AS visibility_observations,

            AVG(precipitation_mm) AS mean_precipitation_mm,
            COUNT(precipitation_mm) AS precipitation_observations,

            AVG(wind_speed_m_s) AS mean_wind_speed_m_s,
            MAX(wind_gust_m_s) AS max_wind_gust_m_s,

            SUM(scheduled_flights) AS scheduled_flights,
            SUM(cancellations) AS cancellations,
            SUM(departed_flights) AS departed_flights,

            AVG(mean_departure_delay_min)
                AS avg_hourly_mean_departure_delay_min,

            AVG(departure_15min_late_rate)
                AS avg_hourly_15min_late_rate,

            COUNT(departure_15min_late_rate)
                AS flight_observed_hours

        FROM airport_hourly_panel
        WHERE {filter_sql}
          {extra_sql}
        GROUP BY airport
        ORDER BY airport
    """

    summary = execute_query(sql, params)

    return {
        "metadata": _metadata(
            "airport_hourly_panel",
            "airport-hour",
            airport_list,
            start,
            end,
            (
                "Filtered summary of aligned security, weather, "
                "and BTS flight observations. Descriptive "
                "co-occurrence only."
            ),
        ),
        "filters": {
            "start_hour": start_hour,
            "end_hour": end_hour,
            "day_type": day_type,
            "queue_type": queue_type,
        },
        "summary": summary,
        "interpretation_notes": [
            "The panel has one row per airport-hour.",
            "Security and weather fields can be missing independently.",
            "Security percentiles describe hourly airport-level estimates, "
            "not individual passenger waits.",
            "Flight metrics are grouped by scheduled departure hour.",
            "The average of hourly delay rates is not necessarily the "
            "period-wide flight delay rate.",
            "FAA daily data is intentionally excluded.",
            "Co-occurrence does not establish causation.",
        ],
    }