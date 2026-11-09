
from pathlib import Path
import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "processed" / "gatewise.duckdb"

con = duckdb.connect(str(DB_PATH), read_only=True)

queries = {
    "Airport-day panel": """
        SELECT
            airport,
            COUNT(*) AS days,
            ROUND(AVG(departure_15min_late_rate), 3)
                AS avg_flight_delay_rate,
            ROUND(AVG(weighted_avg_wait_min), 2)
                AS avg_security_wait_min,
            ROUND(AVG(avg_temperature_c), 2)
                AS avg_temperature_c,
            ROUND(AVG(delays_per_100_ops), 3)
                AS faa_delays_per_100_ops
        FROM airport_daily_panel
        GROUP BY airport
        ORDER BY airport
    """,

    "Airport-hour panel": """
        SELECT
            airport,
            COUNT(*) AS hours,
            COUNT(weighted_avg_wait_min)
                AS hours_with_security_data,
            COUNT(temperature_c)
                AS hours_with_weather_data,
            COUNT(departure_15min_late_rate)
                AS hours_with_flight_data,
            ROUND(AVG(weighted_avg_wait_min), 2)
                AS avg_security_wait_min
        FROM airport_hourly_panel
        GROUP BY airport
        ORDER BY airport
    """,

    "Missing values in daily panel": """
        SELECT
            airport,
            COUNT(*) AS total_days,
            COUNT(*) FILTER (
                WHERE weighted_avg_wait_min IS NULL
            ) AS missing_security_days,
            COUNT(*) FILTER (
                WHERE departure_15min_late_rate IS NULL
            ) AS missing_flight_days,
            COUNT(*) FILTER (
                WHERE avg_temperature_c IS NULL
            ) AS missing_weather_days,
            COUNT(*) FILTER (
                WHERE total_ops IS NULL
            ) AS missing_faa_days
        FROM airport_daily_panel
        GROUP BY airport
        ORDER BY airport
    """
}

for title, query in queries.items():
    print(f"\n{'=' * 65}")
    print(title.upper())
    print("=" * 65)
    print(con.execute(query).df().to_string(index=False))

con.close()
