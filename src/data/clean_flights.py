
import pandas as pd

from src.data.common import (
    RAW, START, END_EXCLUSIVE, AIRPORTS,
    require_columns, save_parquet
)

SOURCE_DIR = RAW / "flight_performance"


def hhmm_to_hour(series):
    """Convert BTS HHMM scheduled departure values to an integer hour."""
    value = pd.to_numeric(series, errors="coerce")

    valid = value.between(0, 2359) & (value % 100 < 60)
    hour = (value // 100).where(valid)

    return hour.astype("Int64")


def main():
    files = sorted(SOURCE_DIR.glob("*.csv"))

    if not files:
        raise FileNotFoundError(
            f"No monthly BTS CSV files found in {SOURCE_DIR}"
        )

    frames = []

    for path in files:
        print(f"Reading {path.name}")

        part = pd.read_csv(path, low_memory=False)
        part.columns = [
            str(c).strip().replace("\ufeff", "")
            for c in part.columns
        ]

        frames.append(part)

    df = pd.concat(frames, ignore_index=True)

    # Validate against your actual BTS column names.
    required = [
        "FL_DATE",
        "ORIGIN",
        "CRS_DEP_TIME",
        "DEP_TIME",
        "DEP_DELAY",
        "DEP_DEL15",
        "CANCELLED",
        "DIVERTED",
        "DEST",
        "OP_UNIQUE_CARRIER",
    ]

    require_columns(df, required, "BTS flights")

    # --------------------------------------------------
    # 1. Standardize dates and airport identifiers
    # --------------------------------------------------

    df["flight_date"] = pd.to_datetime(
        df["FL_DATE"],
        errors="coerce"
    )

    df["airport"] = (
        df["ORIGIN"]
        .astype("string")
        .str.upper()
        .str.strip()
    )

    df = df[
        df["airport"].isin(AIRPORTS)
        & (df["flight_date"] >= START)
        & (df["flight_date"] < END_EXCLUSIVE)
    ].copy()

    # --------------------------------------------------
    # 2. Clean flight status and departure metrics
    # --------------------------------------------------

    for col in ["CANCELLED", "DIVERTED"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["cancelled"] = df["CANCELLED"].eq(1)
    df["diverted"] = df["DIVERTED"].eq(1)

    df["scheduled_departure_hour"] = hhmm_to_hour(
        df["CRS_DEP_TIME"]
    )

    df["departure_delay_min"] = pd.to_numeric(
        df["DEP_DELAY"],
        errors="coerce"
    )

    df["actual_departure_time"] = pd.to_numeric(
        df["DEP_TIME"],
        errors="coerce"
    )

    df["departure_15min_late"] = pd.to_numeric(
        df["DEP_DEL15"],
        errors="coerce"
    )

    # A flight is considered departed if it has an actual
    # departure time and was not cancelled.
    df["departed"] = (
        df["actual_departure_time"].notna()
        & ~df["cancelled"]
    )
        # Only use flights that actually departed and have a valid delay value.
    df["valid_departure_delay"] = (
        df["departed"] & df["departure_delay_min"].notna()
    )

    df["observed_departure_delay_min"] = (
        df["departure_delay_min"].where(df["valid_departure_delay"])
    )

    # Only include departed flights with a valid DEP_DEL15 classification.
    df["valid_delay_classification"] = (
        df["departed"] & df["departure_15min_late"].notna()
    )

    df["flights_15min_late_flag"] = (
        df["departed"] & (df["departure_15min_late"] == 1)
    ).astype(int)

    # --------------------------------------------------
    # 3. Create flight-level cleaned dataset
    # --------------------------------------------------

    clean = df[
        [
            "airport",
            "flight_date",
            "scheduled_departure_hour",
            "OP_UNIQUE_CARRIER",
            "DEST",
            "CRS_DEP_TIME",
            "DEP_TIME",
            "departure_delay_min",
            "departure_15min_late",
            "cancelled",
            "diverted",
            "departed",
        ]
    ].copy()

    clean = clean.rename(columns={
        "OP_UNIQUE_CARRIER": "airline",
        "DEST": "destination",
        "CRS_DEP_TIME": "scheduled_departure_time",
        "DEP_TIME": "actual_departure_time_raw",
    })

    clean["flight_date"] = (
        clean["flight_date"].dt.strftime("%Y-%m-%d")
    )

    clean["month"] = pd.to_datetime(
        clean["flight_date"]
    ).dt.to_period("M").astype("string")

    clean = clean.sort_values(
        ["airport", "flight_date", "scheduled_departure_hour"]
    ).reset_index(drop=True)

    save_parquet(clean, "flights_clean.parquet")

    # --------------------------------------------------
    # 4. Aggregate to airport-day level
    # --------------------------------------------------

    daily = (
        df.groupby(["airport", "flight_date"], dropna=False)
        .agg(
            scheduled_flights=("airport", "size"),
            cancellations=("cancelled", "sum"),
            departed_flights=("departed", "sum"),

            mean_departure_delay_min=(
                "observed_departure_delay_min", "mean"
            ),
            delay_observations=(
                "observed_departure_delay_min", "count"
            ),

            median_departure_delay_min=(
                "observed_departure_delay_min", "median"
            ),

            flights_15min_late=(
                "flights_15min_late_flag", "sum"
            ),
            classified_departed_flights=(
                "valid_delay_classification", "sum"
            ),
        )
        .reset_index()
    )

    daily["cancellation_rate"] = (
        daily["cancellations"] / daily["scheduled_flights"]
    )

    daily["departure_15min_late_rate"] = (
        daily["flights_15min_late"]
        / daily["classified_departed_flights"].replace(0, pd.NA)
    )

    daily["flight_date"] = (
        daily["flight_date"].dt.strftime("%Y-%m-%d")
    )

    save_parquet(daily, "flight_performance_daily.parquet")

    # --------------------------------------------------
    # 5. Aggregate to airport-scheduled-hour level
    # --------------------------------------------------
    hourly = (
        df.groupby(
            ["airport", "flight_date", "scheduled_departure_hour"],
            dropna=False
        )
        .agg(
            scheduled_flights=("airport", "size"),
            cancellations=("cancelled", "sum"),
            departed_flights=("departed", "sum"),

            mean_departure_delay_min=(
                "observed_departure_delay_min", "mean"
            ),
            delay_observations=(
                "observed_departure_delay_min", "count"
            ),

            flights_15min_late=(
                "flights_15min_late_flag", "sum"
            ),
            classified_departed_flights=(
                "valid_delay_classification", "sum"
            ),
        )
        .reset_index()
    )

    hourly["cancellation_rate"] = (
        hourly["cancellations"] / hourly["scheduled_flights"]
    )

    hourly["departure_15min_late_rate"] = (
        hourly["flights_15min_late"]
        / hourly["classified_departed_flights"].replace(0, pd.NA)
    )

    hourly["flight_date"] = (
        hourly["flight_date"].dt.strftime("%Y-%m-%d")
    )

    save_parquet(hourly, "flight_performance_hourly.parquet")

    # --------------------------------------------------
    # 6. Print validation information
    # --------------------------------------------------

    print("\nFlight-level records by airport:")
    print(clean.groupby("airport").size().to_string())

    print("\nDate coverage:")
    print(
        clean.groupby("airport")["flight_date"]
        .agg(["min", "max"])
        .to_string()
    )

    print("\nDaily records by airport:")
    print(daily.groupby("airport").size().to_string())

    print("\nHourly records by airport:")
    print(hourly.groupby("airport").size().to_string())


if __name__ == "__main__":
    main()
