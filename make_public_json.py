# make_public_json.py: turns the synthetic CSVs into {"data": [...]} JSON for Zetaris
import csv
import json
import os

import requests

os.makedirs("data/public", exist_ok=True)


def convert(value):
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def write(name, rows):
    path = f"data/public/{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"data": rows}, f, separators=(",", ":"))
    print(f"{name}: {len(rows)} rows, {os.path.getsize(path) / 1024:.0f} KB")


for name in ("sales", "waste"):
    with open(f"data/{name}.csv", newline="", encoding="utf-8") as f:
        rows = [{k: convert(v) for k, v in row.items()} for row in csv.DictReader(f)]
    write(name, rows)

# Weather: real Melbourne daily rainfall from Open-Meteo (free, no key)
w = requests.get(
    "https://archive-api.open-meteo.com/v1/archive",
    params={
        "latitude": -37.8136,
        "longitude": 144.9631,
        "start_date": "2026-01-01",
        "end_date": "2026-10-15",
        "daily": "precipitation_sum",
        "timezone": "Australia/Melbourne",
    },
    timeout=60,
).json()["daily"]
write(
    "weather",
    [
        {"date": d, "precipitation_mm": p if p is not None else 0.0}
        for d, p in zip(w["time"], w["precipitation_sum"])
    ],
)

# Holidays: Nager.Date, national plus Victoria
h = requests.get("https://date.nager.at/api/v3/PublicHolidays/2026/AU", timeout=60).json()
write(
    "holidays",
    [
        {"date": x["date"], "holiday_name": x["name"]}
        for x in h
        if x.get("global") or "AU-VIC" in (x.get("counties") or [])
    ],
)