import pandas as pd
from src.data.common import RAW

SOURCE = RAW / "FAA" / "WEB-Report-22032.xls"

def main():
    # Despite the .xls extension, this file was identified as HTML.
    tables = pd.read_html(SOURCE, header=None)
    print(f"Found {len(tables)} HTML tables.")
    for i, table in enumerate(tables):
        print(f"\nTABLE {i}: shape={table.shape}")
        print(table.head(15).to_string(index=False, header=False))
        print("\nColumn count:", len(table.columns))

if __name__ == "__main__":
    main()
