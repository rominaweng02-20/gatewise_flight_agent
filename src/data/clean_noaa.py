import pandas as pd
from src.data.common import RAW, START, END_EXCLUSIVE, AIRPORTS, require_columns, save_parquet

SOURCE_DIR = RAW / "noaa"
FILE_TO_AIRPORT = {
    "EWR_Weather_2026.csv": "EWR",
    "JFK_Weather_2026.csv": "JFK",
    "LGA_Weather_2026.csv": "LGA",
}

def numeric_with_trace(series):
    """Return numeric precipitation and a separate trace flag; trace is not zero."""
    raw = series.astype("string").str.strip()
    trace = raw.str.upper().eq("T").fillna(False)
    numeric = pd.to_numeric(raw.mask(trace), errors="coerce")
    return numeric, trace

def main():
    outputs = []
    for filename, airport in FILE_TO_AIRPORT.items():
        path = SOURCE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(path)

        df = pd.read_csv(path, low_memory=False)
        df.columns = [str(c).strip().replace("\\ufeff", "") for c in df.columns]
        required = [
            "DATE", "REPORT_TYPE", "HourlyDryBulbTemperature",
            "HourlyPrecipitation", "HourlyVisibility",
            "HourlyWindSpeed", "HourlyWindGustSpeed",
            "HourlyPresentWeatherType"
        ]
        require_columns(df, required, f"NOAA {airport}")

        # LCDv2 station-year CSV observations are GHCNh-based and use SI/metric units.
        # GHCNh observation timestamps are UTC; convert to New York local time before hour bucketing.
        timestamp_utc = pd.to_datetime(df["DATE"], errors="coerce", utc=True)
        df["observation_time_utc"] = timestamp_utc
        df["observation_time_et"] = timestamp_utc.dt.tz_convert("America/New_York")
        df = df[
            (df["observation_time_et"] >= START.tz_localize("America/New_York"))
            & (df["observation_time_et"] < END_EXCLUSIVE.tz_localize("America/New_York"))
        ].copy()

        # Keep only routine FM-15 observations in the primary table.
        # FM-16 is saved separately so it cannot overweight hours with special reports.
        df["REPORT_TYPE"] = df["REPORT_TYPE"].astype("string").str.strip()
        df = df[df["REPORT_TYPE"].isin(["FM-15", "FM-16"])].copy()

        for col in [
            "HourlyDryBulbTemperature", "HourlyVisibility",
            "HourlyWindSpeed", "HourlyWindGustSpeed"
        ]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["precipitation_mm"], df["precipitation_trace"] = numeric_with_trace(
            df["HourlyPrecipitation"]
        )
        df["airport"] = airport
        df["hour_et"] = df["observation_time_et"].dt.floor("h")

        clean = df.rename(columns={
            "HourlyDryBulbTemperature": "temperature_c",
            "HourlyVisibility": "visibility_km",
            "HourlyWindSpeed": "wind_speed_m_s",
            "HourlyWindGustSpeed": "wind_gust_m_s",
            "HourlyPresentWeatherType": "present_weather",
        })

        keep = [
            "airport", "REPORT_TYPE", "observation_time_utc",
            "observation_time_et", "hour_et", "temperature_c",
            "precipitation_mm", "precipitation_trace", "visibility_km",
            "wind_speed_m_s", "wind_gust_m_s", "present_weather"
        ]
        outputs.append(clean[keep])

    all_weather = pd.concat(outputs, ignore_index=True)
    all_weather = all_weather.sort_values(["airport", "observation_time_utc"])

    primary = all_weather[all_weather["REPORT_TYPE"] == "FM-15"].copy()
    special = all_weather[all_weather["REPORT_TYPE"] == "FM-16"].copy()

    # Keep observation-level primary data; create an airport-hour table separately.
    save_parquet(primary, "weather_fm15_observations.parquet")
    save_parquet(special, "weather_fm16_observations.parquet")

    # Most FM-15 reports are hourly. Aggregate if multiple observations land in one local hour.
    # Precipitation is deliberately not summed: NOAA hourly precipitation may be a running/
    # interval amount. Retain max numeric amount and trace indicator as descriptive flags.
    hourly = (
        primary.groupby(["airport", "hour_et"], dropna=False)
        .agg(
            temperature_c=("temperature_c", "mean"),
            precipitation_mm=("precipitation_mm", "max"),
            precipitation_trace=("precipitation_trace", "max"),
            visibility_km=("visibility_km", "min"),
            wind_speed_m_s=("wind_speed_m_s", "mean"),
            wind_gust_m_s=("wind_gust_m_s", "max"),
            weather_report_count=("REPORT_TYPE", "size"),
            present_weather=("present_weather", lambda s: " | ".join(
                sorted(set(x for x in s.dropna().astype(str) if x.strip()))
            ) or pd.NA),
        )
        .reset_index()
    )
    save_parquet(hourly, "weather_hourly.parquet")

    print("\nNOAA FM-15 hourly coverage:")
    print(hourly.groupby("airport").agg(
        hours=("hour_et", "nunique"),
        first_hour=("hour_et", "min"),
        last_hour=("hour_et", "max")
    ).to_string())

if __name__ == "__main__":
    main()
