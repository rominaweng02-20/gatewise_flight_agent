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
) -> dict:
    """Analyze flight departure reliability at daily, hourly, or monthly grain."""

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    if grain not in {"daily", "hourly", "monthly"}:
        raise ValueError("grain must be 'daily', 'hourly', or 'monthly'.")

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

    else:
        if grain == "daily":
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

        else:  # hourly
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

    filter_sql, params = build_filter_sql(
        airport_list,
        start,
        end,
        date_column=date_column,
    )

    grouping_sql = f"GROUP BY {group_by}" if group_by else ""

    sql = f"""
        SELECT
            airport,
            {select_columns}
        FROM {table}
        WHERE {filter_sql}
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
        "rows": rows,
        "interpretation_notes": [
            "Cancellation rate uses scheduled flights as its denominator.",
            "Departure 15-minute-late rate uses classified departed flights.",
            "Mean departure delay is weighted by valid delay observations.",
            "Monthly median departure delay is not calculated by averaging "
            "daily medians.",
            "Hourly records are grouped by scheduled departure hour, "
            "not actual departure hour.",
            "Missing hourly records are not interpreted as zero-delay "
            "observations.",
        ],
    }

def security_patterns(
    airports: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    grain: str = "daily",
) -> dict:
    """Analyze airport security wait patterns and sample coverage."""

    airport_list, start, end = _validate_inputs(
        airports, start_date, end_date
    )

    if grain not in {"daily", "hourly"}:
        raise ValueError("grain must be 'daily' or 'hourly'.")

    if grain == "daily":
        table = "security_airport_daily"
        date_column = "date"
        time_column = "date"

        select_columns = """
            date,
            weighted_avg_wait_min,
            total_samples,
            observed_hours,
            terminal_count
        """

        order_column = "date"

    else:
        table = "security_airport_hourly"
        date_column = "CAST(hour_et AS DATE)"
        time_column = "hour_et"

        select_columns = """
            hour_et,
            weighted_avg_wait_min,
            standard_weighted_avg_wait_min,
            precheck_weighted_avg_wait_min,
            total_samples,
            terminal_count,
            terminal_queue_records
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
) -> dict:
    """
    Explore hourly co-occurrence of security, weather, and flight metrics.

    This is descriptive association, not a causal analysis.
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
            hour_et,
            hour_of_day,
            day_of_week,

            weighted_avg_wait_min,
            standard_weighted_avg_wait_min,
            precheck_weighted_avg_wait_min,
            security_samples,
            terminal_count,

            temperature_c,
            precipitation_mm,
            precipitation_trace,
            visibility_km,
            wind_speed_m_s,
            wind_gust_m_s,
            weather_report_count,

            scheduled_flights,
            cancellations,
            departed_flights,
            mean_departure_delay_min,
            flights_15min_late,
            cancellation_rate,
            departure_15min_late_rate

        FROM airport_hourly_panel
        WHERE {filter_sql}
        ORDER BY airport, hour_et
    """

    rows = execute_query(sql, params)

    return {
        "metadata": _metadata(
            "airport_hourly_panel",
            "airport-hour",
            airport_list,
            start,
            end,
            (
                "Aligned hourly observations of security waits, NOAA "
                "weather, and BTS flight performance. This supports "
                "descriptive co-occurrence analysis only."
            ),
        ),
        "rows": rows,
        "interpretation_notes": [
            "The panel has one row per airport-hour.",
            "Security and weather fields can be missing independently.",
            "Flight metrics are grouped by scheduled departure hour.",
            "FAA daily data is intentionally excluded from this hourly panel.",
            "Co-occurrence does not establish that security queues or "
            "weather caused a particular flight delay."
        ],
    }