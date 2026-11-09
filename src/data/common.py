from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

AIRPORTS = {"JFK", "EWR", "LGA"}
START = pd.Timestamp("2026-04-01")
END_EXCLUSIVE = pd.Timestamp("2026-09-01")

def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]
    return df

def require_columns(df, required, source):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{source}: missing required columns {missing}. "
            f"Available columns: {list(df.columns)}"
        )

def save_parquet(df, filename):
    path = PROCESSED / filename
    df.to_parquet(path, index=False)
    print(f"Saved {len(df):,} rows -> {path}")
    return path
