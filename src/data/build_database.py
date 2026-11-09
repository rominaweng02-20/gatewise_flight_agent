
from pathlib import Path
import duckdb


# ==================================================
# Configuration
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data" / "processed"
DB_PATH = DATA_DIR / "gatewise.duckdb"

AIRPORTS = ["EWR", "JFK", "LGA"]


# ==================================================
# Source datasets
# ==================================================

PARQUET_FILES = {
    "flights_clean": "flights_clean.parquet",
    "flight_performance_daily": "flight_performance_daily.parquet",
    "flight_performance_hourly": "flight_performance_hourly.parquet",
    "security_waits_hourly": "security_waits_clean.parquet",
    "weather_fm15_observations": "weather_fm15_observations.parquet",
    "weather_fm16_observations": "weather_fm16_observations.parquet",
    "weather_hourly": "weather_hourly.parquet",
    "faa_operations_daily": "faa_operations_daily.parquet",
}


# ==================================================
# Load source tables
# ==================================================

def load_source_tables(con):

    print("\nLOADING SOURCE TABLES")
    print("-" * 60)

    for table_name, filename in PARQUET_FILES.items():

        file_path = DATA_DIR / filename

        if not file_path.exists():
            raise FileNotFoundError(
                f"Missing dataset: {file_path}"
            )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT *
            FROM read_parquet(?)
            """,
            [str(file_path)]
        )

        count = con.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        print(f"{table_name:<35} {count:>10,} rows")


# ==================================================
# Create analytical views
# ==================================================

def create_security_views(con):

    print("\nCREATING SECURITY VIEWS")

    # Aggregate terminal and queue records into one
    # airport-hour record using sample-weighted means.
    #
    # Do not average terminal-level percentiles:
    # they are not pooled airport-level percentiles.

    con.execute("""
        CREATE OR REPLACE VIEW security_airport_hourly AS

        SELECT
            airport,
            hour_et,

            SUM(avg_wait * n_samples)
                / NULLIF(SUM(n_samples), 0)
                AS weighted_avg_wait_min,

            SUM(
                CASE WHEN queue_type = 'standard'
                THEN avg_wait * n_samples END
            )
            / NULLIF(
                SUM(
                    CASE WHEN queue_type = 'standard'
                    THEN n_samples END
                ), 0
            ) AS standard_weighted_avg_wait_min,

            SUM(
                CASE WHEN queue_type = 'precheck'
                THEN avg_wait * n_samples END
            )
            / NULLIF(
                SUM(
                    CASE WHEN queue_type = 'precheck'
                    THEN n_samples END
                ), 0
            ) AS precheck_weighted_avg_wait_min,

            SUM(n_samples) AS total_samples,

            COUNT(DISTINCT terminal) AS terminal_count,

            COUNT(*) AS terminal_queue_records

        FROM security_waits_hourly

        GROUP BY airport, hour_et
    """)

    # Daily security experience.
    con.execute("""
        CREATE OR REPLACE VIEW security_airport_daily AS

        SELECT
            airport,
            CAST(hour_et AS DATE) AS date,

            SUM(avg_wait * n_samples)
                / NULLIF(SUM(n_samples), 0)
                AS weighted_avg_wait_min,

            SUM(n_samples) AS total_samples,

            COUNT(DISTINCT hour_et) AS observed_hours,

            COUNT(DISTINCT terminal) AS terminal_count

        FROM security_waits_hourly

        GROUP BY airport, CAST(hour_et AS DATE)
    """)


def create_weather_views(con):

    print("CREATING WEATHER VIEWS")

    # Weather timestamps are timezone-aware.
    # Convert them into Eastern local wall-clock time
    # to match the security timestamps.

    con.execute("""
        CREATE OR REPLACE VIEW weather_hourly_local AS

        SELECT
            airport,

            timezone(
                'America/New_York',
                hour_et
            ) AS hour_et,

            temperature_c,
            precipitation_mm,
            precipitation_trace,
            visibility_km,
            wind_speed_m_s,
            wind_gust_m_s,
            weather_report_count,
            present_weather

        FROM weather_hourly
    """)

    # Daily weather summary.
    # Missing precipitation remains NULL when there
    # are no reported precipitation measurements.

    con.execute("""
        CREATE OR REPLACE VIEW weather_airport_daily AS

        SELECT
            airport,
            CAST(hour_et AS DATE) AS date,

            AVG(temperature_c) AS avg_temperature_c,

            MIN(visibility_km) AS min_visibility_km,

            AVG(visibility_km) AS avg_visibility_km,

            MAX(wind_speed_m_s) AS max_wind_speed_m_s,

            MAX(wind_gust_m_s) AS max_wind_gust_m_s,

            SUM(precipitation_mm) AS reported_precipitation_mm,

            COUNT(*) AS weather_hours,

            COUNT(precipitation_mm)
                AS precipitation_report_hours,

            SUM(
                CASE WHEN precipitation_trace
                THEN 1 ELSE 0 END
            ) AS precipitation_trace_hours

        FROM weather_hourly_local

        GROUP BY airport, CAST(hour_et AS DATE)
    """)


def create_flight_views(con):

    print("CREATING FLIGHT VIEWS")

    # Normalize daily flight dates.

    con.execute("""
        CREATE OR REPLACE VIEW flight_daily AS

        SELECT
            airport,
            CAST(flight_date AS DATE) AS date,
            scheduled_flights,
            cancellations,
            departed_flights,
            delay_observations,
            classified_departed_flights,
            mean_departure_delay_min,
            median_departure_delay_min,
            flights_15min_late,
            cancellation_rate,
            departure_15min_late_rate
        FROM flight_performance_daily
    """)

    # Convert scheduled departure hours into Eastern
    # local airport-hour timestamps.

    con.execute("""
        CREATE OR REPLACE VIEW flight_hourly AS

        SELECT
            airport,
            CAST(flight_date AS DATE) AS date,
            scheduled_departure_hour,

            CAST(flight_date AS DATE)::TIMESTAMP
                + scheduled_departure_hour * INTERVAL '1 hour'
                AS hour_et,

            scheduled_flights,
            cancellations,
            departed_flights,
            mean_departure_delay_min,
            flights_15min_late,
            cancellation_rate,
            departure_15min_late_rate,
            delay_observations,
            classified_departed_flights

        FROM flight_performance_hourly

        WHERE scheduled_departure_hour IS NOT NULL
    """)


# ==================================================
# Airport-hour analytical panel
# ==================================================

def create_hourly_panel(con):

    print("CREATING AIRPORT-HOUR PANEL")

    # Build a complete set of observed airport-hour keys
    # from all three hourly sources.
    #
    # This prevents records from disappearing simply
    # because one source is missing an observation.

    con.execute("""
        CREATE OR REPLACE VIEW airport_hourly_panel AS

        WITH all_hours AS (

            SELECT airport, hour_et
            FROM security_airport_hourly

            UNION

            SELECT airport, hour_et
            FROM weather_hourly_local

            UNION

            SELECT airport, hour_et
            FROM flight_hourly
        )

        SELECT

            h.airport,
            h.hour_et,
            CAST(h.hour_et AS DATE) AS date,

            EXTRACT(HOUR FROM h.hour_et)
                AS hour_of_day,

            EXTRACT(DOW FROM h.hour_et)
                AS day_of_week,

            s.weighted_avg_wait_min,
            s.standard_weighted_avg_wait_min,
            s.precheck_weighted_avg_wait_min,
            s.total_samples AS security_samples,
            s.terminal_count,
            s.terminal_queue_records,

            w.temperature_c,
            w.precipitation_mm,
            w.precipitation_trace,
            w.visibility_km,
            w.wind_speed_m_s,
            w.wind_gust_m_s,
            w.weather_report_count,
            w.present_weather,

            f.scheduled_flights,
            f.cancellations,
            f.departed_flights,
            f.mean_departure_delay_min,
            f.flights_15min_late,
            f.cancellation_rate,
            f.departure_15min_late_rate

        FROM all_hours h

        LEFT JOIN security_airport_hourly s
            ON h.airport = s.airport
            AND h.hour_et = s.hour_et

        LEFT JOIN weather_hourly_local w
            ON h.airport = w.airport
            AND h.hour_et = w.hour_et

        LEFT JOIN flight_hourly f
            ON h.airport = f.airport
            AND h.hour_et = f.hour_et
    """)


# ==================================================
# Airport-day analytical panel
# ==================================================

def create_daily_panel(con):

    print("CREATING AIRPORT-DAY PANEL")

    con.execute("""
        CREATE OR REPLACE VIEW airport_daily_panel AS

        WITH all_dates AS (

            SELECT airport, date
            FROM faa_operations_daily

            UNION

            SELECT airport, date
            FROM flight_daily

            UNION

            SELECT airport, date
            FROM security_airport_daily

            UNION

            SELECT airport, date
            FROM weather_airport_daily
        )

        SELECT

            d.airport,
            d.date,

            -- BTS flight reliability
            f.scheduled_flights,
            f.cancellations,
            f.departed_flights,
            f.mean_departure_delay_min,
            f.median_departure_delay_min,
            f.flights_15min_late,
            f.cancellation_rate,
            f.departure_15min_late_rate,

            -- Security experience
            s.weighted_avg_wait_min,
            s.total_samples AS security_samples,
            s.observed_hours AS security_observed_hours,

            -- Weather
            w.avg_temperature_c,
            w.min_visibility_km,
            w.avg_visibility_km,
            w.max_wind_speed_m_s,
            w.max_wind_gust_m_s,
            w.reported_precipitation_mm,
            w.weather_hours,
            w.precipitation_report_hours,
            w.precipitation_trace_hours,

            -- FAA operational performance
            a.total_ops,
            a.total_delays,
            a.delay_rate AS faa_delay_rate,

            -- Calculate the aggregate delay rate directly
            -- from the daily FAA operational counts.
            100.0 * a.total_delays
                / NULLIF(a.total_ops, 0) AS delays_per_100_ops,

            a.cause_weather,

            EXTRACT(DOW FROM d.date) AS day_of_week,

            CASE
                WHEN EXTRACT(DOW FROM d.date) IN (0, 6)
                THEN TRUE
                ELSE FALSE
            END AS is_weekend

        FROM all_dates d

        LEFT JOIN flight_daily f
            ON d.airport = f.airport
            AND d.date = f.date

        LEFT JOIN security_airport_daily s
            ON d.airport = s.airport
            AND d.date = s.date

        LEFT JOIN weather_airport_daily w
            ON d.airport = w.airport
            AND d.date = w.date

        LEFT JOIN faa_operations_daily a
            ON d.airport = a.airport
            AND d.date = CAST(a.date AS DATE)
    """)


# ==================================================
# Validation
# ==================================================

def validate_database(con):

    print("\nDATABASE VALIDATION")
    print("=" * 65)

    checks = {
        "FAA daily": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, CAST(date AS DATE)
                FROM faa_operations_daily
                GROUP BY airport, CAST(date AS DATE)
                HAVING COUNT(*) > 1
            )
        """,

        "Flight daily": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, CAST(flight_date AS DATE)
                FROM flight_performance_daily
                GROUP BY airport, CAST(flight_date AS DATE)
                HAVING COUNT(*) > 1
            )
        """,

        "Weather hourly": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, hour_et
                FROM weather_hourly_local
                GROUP BY airport, hour_et
                HAVING COUNT(*) > 1
            )
        """,

        "Security hourly": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, hour_et
                FROM security_airport_hourly
                GROUP BY airport, hour_et
                HAVING COUNT(*) > 1
            )
        """,

        "Flight hourly": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, hour_et
                FROM flight_hourly
                GROUP BY airport, hour_et
                HAVING COUNT(*) > 1
            )
        """,

        "Airport-hour panel": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, hour_et
                FROM airport_hourly_panel
                GROUP BY airport, hour_et
                HAVING COUNT(*) > 1
            )
        """,

        "Airport-day panel": """
            SELECT COUNT(*)
            FROM (
                SELECT airport, date
                FROM airport_daily_panel
                GROUP BY airport, date
                HAVING COUNT(*) > 1
            )
        """,
    }

    for name, query in checks.items():

        result = con.execute(query).fetchone()[0]

        status = "PASS" if result == 0 else "FAIL"

        print(f"{name:<30} {status} ({result} duplicates)")

        if result > 0:
            raise ValueError(
                f"Duplicate keys found in {name}"
            )

    print("\nPANEL ROW COUNTS")

    for view in [
        "airport_hourly_panel",
        "airport_daily_panel",
    ]:

        result = con.execute(
            f"SELECT COUNT(*) FROM {view}"
        ).fetchone()[0]

        print(f"{view:<30} {result:>10,} rows")

    print("\nDAILY PANEL AIRPORT COVERAGE")

    print(
        con.execute("""
            SELECT
                airport,
                COUNT(*) AS days,
                MIN(date) AS first_date,
                MAX(date) AS last_date
            FROM airport_daily_panel
            GROUP BY airport
            ORDER BY airport
        """).df().to_string(index=False)
    )

    print("\nHOURLY PANEL AIRPORT COVERAGE")

    print(
        con.execute("""
            SELECT
                airport,
                COUNT(*) AS hours,
                MIN(hour_et) AS first_hour,
                MAX(hour_et) AS last_hour
            FROM airport_hourly_panel
            GROUP BY airport
            ORDER BY airport
        """).df().to_string(index=False)
    )


# ==================================================
# Main
# ==================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 65)
    print("GATEWISE ANALYTICAL DATABASE BUILDER")
    print("=" * 65)

    con = duckdb.connect(str(DB_PATH))

    try:

        load_source_tables(con)

        create_security_views(con)

        create_weather_views(con)

        create_flight_views(con)

        create_hourly_panel(con)

        create_daily_panel(con)

        validate_database(con)

    finally:

        con.close()

    print("\n" + "=" * 65)
    print("DATABASE BUILD COMPLETE")
    print(f"Database: {DB_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    main()
