from src.analytics import (
    airport_overview,
    flight_reliability,
    security_patterns,
    weather_conditions,
    airport_operations,
    hourly_airport_patterns,
)


def run_test(name, function, **kwargs):
    print(f"\n{'=' * 60}")
    print(f"TEST: {name}")
    print("=" * 60)

    result = function(**kwargs)

    print("Source:", result["metadata"]["source"])
    print("Grain:", result["metadata"]["grain"])

    if "rows" in result:
        print("Rows returned:", len(result["rows"]))
        if result["rows"]:
            print("Example:", result["rows"][0])

    if "summary" in result:
        print("Summary rows:", len(result["summary"]))
        if result["summary"]:
            print("Example:", result["summary"][0])

    if "daily_rows" in result:
        print("Daily rows:", len(result["daily_rows"]))

    print("PASS")


def main():
    common = {
        "airports": ["JFK", "EWR", "LGA"],
        "start_date": "2026-04-01",
        "end_date": "2026-04-07",
    }

    run_test("Airport overview", airport_overview, **common)

    run_test(
        "Daily flight reliability",
        flight_reliability,
        **common,
        grain="daily",
    )

    run_test(
        "Hourly flight reliability",
        flight_reliability,
        **common,
        grain="hourly",
    )

    run_test(
        "Daily security patterns",
        security_patterns,
        **common,
        grain="daily",
    )

    run_test(
        "Hourly security patterns",
        security_patterns,
        **common,
        grain="hourly",
    )

    run_test(
        "Daily weather conditions",
        weather_conditions,
        **common,
        grain="daily",
    )

    run_test(
        "Hourly weather conditions",
        weather_conditions,
        **common,
        grain="hourly",
    )

    run_test("FAA airport operations", airport_operations, **common)

    run_test(
        "Hourly airport patterns",
        hourly_airport_patterns,
        **common,
    )


if __name__ == "__main__":
    main()