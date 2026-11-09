
from pathlib import Path

import pandas as pd


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "FAA"
    / "WEB-Report-22032.xls"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

AIRPORTS = ["JFK", "EWR", "LGA"]

START_DATE = pd.Timestamp("2026-04-01")
END_DATE = pd.Timestamp("2026-08-31")

# Positional mapping based on the five-level OPSNET headers.
COLUMN_NAMES = [
    "airport",
    "date",
    "total_ops",
    "total_delays",
    "tmi_to_delays",
    "occurred_dep_delays",
    "occurred_abrn_delays",
    "tmi_from_local_delays",
    "tmi_from_nonlocal_delays",
    "total_occurred_at_delays",
    "total_local_departures",
    "abrn_dest_to_delays",
    "class_ac",
    "class_at",
    "class_ga",
    "class_mil",
    "cause_weather",
    "cause_volume",
    "cause_equipment",
    "cause_runway",
    "cause_other",
    "avg_delay_minutes",
    "total_delay_minutes",
]

NUMERIC_COLUMNS = COLUMN_NAMES[2:]


# --------------------------------------------------
# Load and clean
# --------------------------------------------------

def load_faa_data():

    if not RAW_FILE.exists():
        raise FileNotFoundError(
            f"FAA source file not found: {RAW_FILE}"
        )

    # The .xls file is actually an HTML report.
    tables = pd.read_html(RAW_FILE, header=None)

    if not tables:
        raise ValueError("No HTML tables found in FAA report.")

    raw = tables[0]

    print(f"Original table shape: {raw.shape}")

    if raw.shape[1] < len(COLUMN_NAMES):
        raise ValueError(
            f"Expected at least {len(COLUMN_NAMES)} columns, "
            f"but found {raw.shape[1]}."
        )

    # Keep the 23 meaningful columns.
    raw = raw.iloc[:, :len(COLUMN_NAMES)].copy()

    # Assign names based on verified column positions.
    raw.columns = COLUMN_NAMES

    # Remove title and multi-level header rows.
    # Actual records have an airport code in column 0
    # and a valid MM/DD/YYYY date in column 1.
    raw["airport"] = raw["airport"].astype(str).str.strip()

    raw["date"] = pd.to_datetime(
        raw["date"],
        format="%m/%d/%Y",
        errors="coerce"
    )

    df = raw[
        raw["airport"].isin(AIRPORTS)
        & raw["date"].notna()
    ].copy()

    # Restrict to the project analysis period.
    df = df[
        (df["date"] >= START_DATE)
        & (df["date"] <= END_DATE)
    ].copy()

    # Convert numerical fields.
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # Standardize date fields.
    df["date"] = df["date"].dt.date
    df["date"] = pd.to_datetime(df["date"])

    # Additional useful fields.
    df["month"] = df["date"].dt.month
    df["day_of_week"] = df["date"].dt.day_of_week
    df["is_weekend"] = df["day_of_week"].isin([5, 6])

    # Delay rate relative to daily airport operations.
    df["delay_rate"] = (
        df["total_delays"] / df["total_ops"].where(df["total_ops"] != 0)
    )

    return df


# --------------------------------------------------
# Data validation
# --------------------------------------------------

def validate_faa_data(df):

    print("\nFAA DATA VALIDATION")
    print("-" * 50)

    # Check duplicate airport-date records.
    duplicates = df.duplicated(
        subset=["airport", "date"]
    ).sum()

    print(f"Duplicate airport-date records: {duplicates}")

    if duplicates > 0:
        raise ValueError(
            "Duplicate airport-date records found."
        )

    # Check missing values in important fields.
    required = [
        "airport",
        "date",
        "total_ops",
        "total_delays",
    ]

    print("\nMissing values in key fields:")
    print(df[required].isna().sum())

    # Check nonnegative values.
    nonnegative_columns = [
        "total_ops",
        "total_delays",
        "total_delay_minutes",
    ]

    for col in nonnegative_columns:
        invalid = (df[col] < 0).sum()

        if invalid > 0:
            print(
                f"WARNING: {invalid} negative values in {col}"
            )

    # Check whether class totals reconcile with total delays.
    class_columns = [
        "class_ac",
        "class_at",
        "class_ga",
        "class_mil",
    ]

    class_sum = df[class_columns].sum(
        axis=1,
        min_count=len(class_columns)
    )

    class_mismatch = (
        class_sum.notna()
        & df["total_delays"].notna()
        & (class_sum != df["total_delays"])
    )

    print(
        "\nAircraft-class reconciliation mismatches:",
        class_mismatch.sum()
    )

    # Check whether cause totals reconcile with total delays.
    cause_columns = [
        "cause_weather",
        "cause_volume",
        "cause_equipment",
        "cause_runway",
        "cause_other",
    ]

    cause_sum = df[cause_columns].sum(
        axis=1,
        min_count=len(cause_columns)
    )

    cause_mismatch = (
        cause_sum.notna()
        & df["total_delays"].notna()
        & (cause_sum != df["total_delays"])
    )

    print(
        "Delay-cause reconciliation mismatches:",
        cause_mismatch.sum()
    )

    # Check average and total delay minutes.
    expected_minutes = (
        df["avg_delay_minutes"] * df["total_delays"]
    )

    minute_mismatch = (
        expected_minutes.notna()
        & df["total_delay_minutes"].notna()
        & (
            (expected_minutes - df["total_delay_minutes"]).abs()
            > 1.0
        )
    )

    print(
        "Average/total delay-minute mismatches:",
        minute_mismatch.sum()
    )

    if duplicates > 0:
        raise ValueError("FAA duplicate records detected.")


# --------------------------------------------------
# Coverage report
# --------------------------------------------------

def create_coverage_report(df):

    coverage = (
        df.groupby("airport")
        .agg(
            daily_records=("date", "nunique"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            total_operations=("total_ops", "sum"),
            total_delays=("total_delays", "sum"),
            average_daily_operations=("total_ops", "mean"),
            average_daily_delays=("total_delays", "mean"),
            average_delay_rate=("delay_rate", "mean"),
            total_delay_minutes=("total_delay_minutes", "sum"),
        )
        .reset_index()
    )
    coverage["delays_per_100_ops"] = (
    coverage["total_delays"]
    / coverage["total_operations"]
    * 100
)
    return coverage


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("Loading FAA OPSNET report...")

    df = load_faa_data()

    print(f"\nCleaned records: {len(df):,}")
    print(
        f"Date coverage: {df['date'].min().date()} "
        f"to {df['date'].max().date()}"
    )

    print("\nRecords by airport:")
    print(df.groupby("airport").size())

    validate_faa_data(df)

    # Save airport-day dataset.
    output_file = OUTPUT_DIR / "faa_operations_daily.parquet"

    df.to_parquet(
        output_file,
        index=False
    )

    print(f"\nSaved: {output_file}")

    # Save coverage report.
    coverage = create_coverage_report(df)

    coverage_file = OUTPUT_DIR / "faa_coverage.csv"

    coverage.to_csv(
        coverage_file,
        index=False
    )

    print(f"Saved: {coverage_file}")

    print("\nFAA AIRPORT SUMMARY")
    print(coverage.to_string(index=False))


if __name__ == "__main__":
    main()
