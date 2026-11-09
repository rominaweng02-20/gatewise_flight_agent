import duckdb

con = duckdb.connect("data/processed/gatewise.duckdb", read_only=True)

for table in ["flight_daily", "flight_hourly"]:
    print(f"\n--- {table.upper()} ---")
    sql = (
        "SELECT COUNT(*) AS total_records, "
        "COUNT(*) FILTER (WHERE delay_observations != departed_flights) AS delay_mismatches, "
        "COUNT(*) FILTER (WHERE classified_departed_flights != departed_flights) AS classification_mismatches "
        f"FROM {table}"
    )
    print(con.execute(sql).df().to_string(index=False))

print("\n--- PERIOD-WIDE FLIGHT COUNTS ---")

sql = (
    "SELECT airport, "
    "SUM(scheduled_flights) AS scheduled_flights, "
    "SUM(cancellations) AS cancellations, "
    "SUM(departed_flights) AS departed_flights, "
    "SUM(delay_observations) AS delay_observations, "
    "SUM(classified_departed_flights) AS classified_departed_flights, "
    "SUM(flights_15min_late) AS flights_15min_late "
    "FROM flight_daily GROUP BY airport ORDER BY airport"
)

print(con.execute(sql).df().to_string(index=False))
con.close()

