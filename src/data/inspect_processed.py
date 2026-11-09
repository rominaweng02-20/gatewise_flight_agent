
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "processed"


def main():
    for path in sorted(DATA_DIR.glob("*.parquet")):
        df = pd.read_parquet(path)

        print("\n" + "=" * 75)
        print(f"FILE: {path.name}")
        print("=" * 75)

        print(f"Rows: {len(df):,}")
        print(f"Columns: {len(df.columns)}")

        print("\nCOLUMN NAMES AND TYPES:")
        for col, dtype in df.dtypes.items():
            print(f"  {col:<35} {dtype}")

        if "airport" in df.columns:
            print("\nAIRPORT COVERAGE:")
            print(df["airport"].value_counts(dropna=False).to_string())

        print("\nDATE/TIME COVERAGE:")
        date_cols = [
            col for col in df.columns
            if any(term in col.lower() for term in
                   ["date", "time", "hour", "timestamp"])
        ]

        for col in date_cols:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                print(
                    f"  {col}: {df[col].min()} "
                    f"-> {df[col].max()}"
                )

        print("\nSAMPLE RECORDS:")
        print(df.head(2).to_string(index=False))

    print("\n" + "=" * 75)
    print("INSPECTION COMPLETE")
    print("=" * 75)


if __name__ == "__main__":
    main()
