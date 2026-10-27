"""Generate synthetic Melbourne café sales and waste data for 1 Jan–15 Oct 2026."""

from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

SEED = 42
START = date(2026, 1, 1)
END = date(2026, 10, 15)
BASELINE_WASTE_RATE = 0.08
RAIN_MM = 5.0
RAIN_SALES_MULT = 0.70
HOLIDAY_SALES_MULT = 0.60
PREP_ERROR_WASTE_MULT = 3.0

DATA_DIR = Path(__file__).resolve().parent
JSON_DIR = DATA_DIR / "json"
PRECIP_CACHE = DATA_DIR / "melbourne_precipitation.json"
HOLIDAY_CACHE = DATA_DIR / "au_vic_holidays_2026.json"

OPEN_METEO_URL = (
    "https://archive-api.open-meteo.com/v1/archive"
    "?latitude=-37.8136&longitude=144.9631"
    "&start_date=2026-01-01&end_date=2026-10-15"
    "&daily=precipitation_sum&timezone=Australia%2FMelbourne"
)
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/2026/AU"

STORES = [
    {"store_id": "CAF-FIT-01", "outdoor_seating": True, "area_type": "suburban"},
    {"store_id": "CAF-STK-02", "outdoor_seating": True, "area_type": "suburban"},
    {"store_id": "CAF-BRU-03", "outdoor_seating": True, "area_type": "suburban"},
    {"store_id": "CAF-COL-04", "outdoor_seating": False, "area_type": "cbd_office"},
    {"store_id": "CAF-BRK-05", "outdoor_seating": False, "area_type": "cbd_office"},
    {"store_id": "CAF-DOC-06", "outdoor_seating": False, "area_type": "cbd_office"},
    {"store_id": "CAF-HAW-07", "outdoor_seating": False, "area_type": "suburban"},
    {"store_id": "CAF-CAM-08", "outdoor_seating": False, "area_type": "suburban"},
]

PRODUCTS = [
    {"product": "Flat White", "price": 5.5, "base_units": 95},
    {"product": "Latte", "price": 5.8, "base_units": 80},
    {"product": "Espresso", "price": 4.0, "base_units": 55},
    {"product": "Banana Bread", "price": 6.5, "base_units": 28},
    {"product": "Ham & Cheese Croissant", "price": 7.2, "base_units": 32},
]

PREP_ERROR_STORE = "CAF-CAM-08"
PREP_ERROR_PRODUCT = "Ham & Cheese Croissant"
PREP_ERROR_START = date(2026, 8, 10)
PREP_ERROR_END = date(2026, 8, 16)

DECOY_STORE = "CAF-HAW-07"
DECOY_START = date(2026, 5, 11)
DECOY_END = date(2026, 5, 17)


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def load_or_fetch(url: str, cache_path: Path):
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def precipitation_by_date(payload: dict) -> dict[str, float]:
    daily = payload["daily"]
    out = {}
    for day, mm in zip(daily["time"], daily["precipitation_sum"]):
        out[day] = 0.0 if mm is None else float(mm)
    return out


def vic_national_holidays(payload: list) -> dict[str, str]:
    holidays = {}
    for item in payload:
        counties = item.get("counties") or []
        if not item.get("global") and "AU-VIC" not in counties:
            continue
        holidays[item["date"]] = item.get("localName") or item.get("name")
    return holidays


def expected_demand(store: dict, product: dict, day: date, rng: random.Random) -> float:
    units = product["base_units"] * (0.85 + 0.30 * rng.random())
    weekday = day.weekday()
    if store["area_type"] == "cbd_office":
        dow = [1.05, 1.12, 1.10, 1.08, 0.95, 0.38, 0.32][weekday]
    else:
        dow = [0.88, 0.92, 0.95, 1.00, 1.10, 1.28, 1.18][weekday]
    month = 1.0 + 0.04 * (1 if day.month in (6, 7, 8) else 0)
    return max(4.0, units * dow * month)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    precip = precipitation_by_date(load_or_fetch(OPEN_METEO_URL, PRECIP_CACHE))
    holidays = vic_national_holidays(load_or_fetch(NAGER_URL, HOLIDAY_CACHE))
    wet_days = sorted(day for day, mm in precip.items() if mm > RAIN_MM and START <= datetime.strptime(day, "%Y-%m-%d").date() <= END)
    holiday_days = sorted(day for day in holidays if START <= datetime.strptime(day, "%Y-%m-%d").date() <= END)

    sales_rows = []
    waste_rows = []

    for day in daterange(START, END):
        day_s = day.isoformat()
        rain_hit = precip.get(day_s, 0.0) > RAIN_MM
        holiday_hit = day_s in holidays

        for store in STORES:
            promo = (
                1
                if store["store_id"] == DECOY_STORE and DECOY_START <= day <= DECOY_END
                else 0
            )
            for product in PRODUCTS:
                expected = expected_demand(store, product, day, rng)
                sales_mult = 1.0
                if rain_hit and store["outdoor_seating"]:
                    sales_mult *= RAIN_SALES_MULT * rng.uniform(0.94, 1.06)
                if holiday_hit and store["area_type"] == "cbd_office":
                    sales_mult *= HOLIDAY_SALES_MULT * rng.uniform(0.94, 1.06)

                waste_rate = min(0.14, max(0.04, rng.gauss(BASELINE_WASTE_RATE, 0.008)))
                # Prep is set before weather is known; holidays are known, so CBD prep scales down.
                prep_mult = HOLIDAY_SALES_MULT if holiday_hit and store["area_type"] == "cbd_office" else 1.0
                units_prepared = max(1, int(round(expected * prep_mult / (1.0 - waste_rate))))
                units_sold = max(0, min(units_prepared, int(round(expected * sales_mult))))
                units_wasted = max(0, units_prepared - units_sold)

                prep_error = (
                    store["store_id"] == PREP_ERROR_STORE
                    and product["product"] == PREP_ERROR_PRODUCT
                    and PREP_ERROR_START <= day <= PREP_ERROR_END
                )
                if prep_error:
                    units_wasted = max(1, int(round(units_wasted * PREP_ERROR_WASTE_MULT)))

                revenue = round(units_sold * product["price"], 2)
                waste_cost = round(units_wasted * product["price"] * 0.45, 2)

                sales_rows.append(
                    {
                        "date": day_s,
                        "store_id": store["store_id"],
                        "outdoor_seating": str(store["outdoor_seating"]).lower(),
                        "area_type": store["area_type"],
                        "product": product["product"],
                        "units_sold": units_sold,
                        "revenue": f"{revenue:.2f}",
                        "promo_flag": promo,
                    }
                )
                waste_rows.append(
                    {
                        "date": day_s,
                        "store_id": store["store_id"],
                        "product": product["product"],
                        "units_wasted": units_wasted,
                        "waste_cost": f"{waste_cost:.2f}",
                    }
                )

    sales_fields = [
        "date",
        "store_id",
        "outdoor_seating",
        "area_type",
        "product",
        "units_sold",
        "revenue",
        "promo_flag",
    ]
    waste_fields = ["date", "store_id", "product", "units_wasted", "waste_cost"]
    write_csv(DATA_DIR / "sales.csv", sales_rows, sales_fields)
    write_csv(DATA_DIR / "waste.csv", waste_rows, waste_fields)

    (JSON_DIR / "sales.json").write_text(json.dumps(sales_rows, indent=2), encoding="utf-8")
    (JSON_DIR / "waste.json").write_text(json.dumps(waste_rows, indent=2), encoding="utf-8")

    answer_key = {
        "true_causes": [
            {
                "cause": "rain_reduces_outdoor_seating_sales",
                "store_ids": [s["store_id"] for s in STORES if s["outdoor_seating"]],
                "dates": wet_days,
                "precipitation_threshold_mm": RAIN_MM,
                "sales_effect": "about 30% lower sales",
                "waste_effect": "waste rises because stores still prepared normal volume",
            },
            {
                "cause": "public_holiday_reduces_cbd_office_sales",
                "store_ids": [s["store_id"] for s in STORES if s["area_type"] == "cbd_office"],
                "dates": holiday_days,
                "holidays": {day: holidays[day] for day in holiday_days},
                "sales_effect": "about 40% lower sales",
            },
            {
                "cause": "prep_error_elevated_waste",
                "store_id": PREP_ERROR_STORE,
                "product": PREP_ERROR_PRODUCT,
                "dates": [d.isoformat() for d in daterange(PREP_ERROR_START, PREP_ERROR_END)],
                "waste_effect": "about 3x normal waste",
                "sales_effect": "none",
            },
        ],
        "decoy": {
            "cause": "promotion_no_effect",
            "store_id": DECOY_STORE,
            "dates": [d.isoformat() for d in daterange(DECOY_START, DECOY_END)],
            "promo_flag": 1,
            "effect": "no real effect on sales or waste",
        },
    }
    (DATA_DIR / "answer_key.json").write_text(json.dumps(answer_key, indent=2), encoding="utf-8")
    (JSON_DIR / "answer_key.json").write_text(json.dumps(answer_key, indent=2), encoding="utf-8")

    print(f"sales.csv rows: {len(sales_rows)}")
    print(f"waste.csv rows: {len(waste_rows)}")
    print(f"wet days (> {RAIN_MM:.0f} mm): {len(wet_days)}")
    print(f"public holidays in range: {len(holiday_days)}")


if __name__ == "__main__":
    main()
