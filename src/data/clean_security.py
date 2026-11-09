import pandas as pd
from src.data.common import RAW, START, END_EXCLUSIVE, AIRPORTS, require_columns, save_parquet

SOURCE = RAW / "security_waits" / "security_waits_hourly.parquet"

def main():
    df = pd.read_parquet(SOURCE)
    required = [
        "airport", "terminal", "queue_type", "hour_et",
        "avg_wait", "p50_wait", "p75_wait", "p95_wait",
        "max_wait", "n_samples"
    ]
    require_columns(df, required, "Security waits")

    df["airport"] = df["airport"].astype("string").str.upper().str.strip()
    df["terminal"] = df["terminal"].astype("string").str.strip()
    df["queue_type"] = df["queue_type"].astype("string").str.lower().str.strip()
    df["hour_et"] = pd.to_datetime(df["hour_et"], errors="coerce")

    df = df[
        df["airport"].isin(AIRPORTS)
        & (df["hour_et"] >= START)
        & (df["hour_et"] < END_EXCLUSIVE)
    ].copy()

    valid_queue_types = {"standard", "precheck"}
    unexpected = set(df["queue_type"].dropna().unique()) - valid_queue_types
    if unexpected:
        raise ValueError(f"Unexpected queue types: {unexpected}")

    key = ["airport", "terminal", "queue_type", "hour_et"]
    duplicates = df.duplicated(key, keep=False)
    if duplicates.any():
        raise ValueError(
            f"Found {duplicates.sum()} duplicate security rows for key {key}. "
            "Resolve duplicates before aggregation; do not silently drop them."
        )

    numeric_cols = ["avg_wait", "p50_wait", "p75_wait", "p95_wait", "max_wait", "n_samples"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if (df["n_samples"].dropna() <= 0).any():
        raise ValueError("n_samples must be positive when present.")
    if (df[["avg_wait", "p50_wait", "p75_wait", "p95_wait", "max_wait"]] < 0).any().any():
        raise ValueError("Negative wait-time value found.")

    df["date_et"] = df["hour_et"].dt.date.astype("string")
    df["month"] = df["hour_et"].dt.to_period("M").astype("string")
    df["day_of_week"] = df["hour_et"].dt.day_name()
    df["hour_of_day"] = df["hour_et"].dt.hour

    # Keep source metrics and n_samples. Do not average percentile columns.
    ordered = [
        "airport", "terminal", "queue_type", "hour_et", "date_et",
        "month", "day_of_week", "hour_of_day", "avg_wait",
        "p50_wait", "p75_wait", "p95_wait", "max_wait", "n_samples"
    ]
    extras = [c for c in df.columns if c not in ordered]
    df = df[ordered + extras].sort_values(key).reset_index(drop=True)

    save_parquet(df, "security_waits_clean.parquet")

    coverage = (
        df.groupby(["airport", "queue_type"], dropna=False)
          .agg(records=("hour_et", "size"),
               unique_hours=("hour_et", "nunique"),
               underlying_samples=("n_samples", "sum"),
               first_hour=("hour_et", "min"),
               last_hour=("hour_et", "max"))
          .reset_index()
    )
    coverage.to_csv((RAW.parent / "processed" / "security_coverage.csv"), index=False) if False else None
    coverage.to_csv((__import__("src.data.common", fromlist=["PROCESSED"]).PROCESSED / "security_coverage.csv"), index=False)
    print("\nSecurity coverage:")
    print(coverage.to_string(index=False))

if __name__ == "__main__":
    main()
