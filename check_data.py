# check_data.py: confirms the planted causes really show up in the data
import csv
import json

key = json.load(open("data/answer_key.json", encoding="utf-8"))
causes = {c["cause"]: c for c in key["true_causes"]}
decoy = key["decoy"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


sales = read("data/sales.csv")
waste = read("data/waste.csv")
weather = json.load(open("data/public/weather.json", encoding="utf-8"))["data"]
holidays = json.load(open("data/public/holidays.json", encoding="utf-8"))["data"]


def avg(vals):
    return sum(vals) / len(vals) if vals else float("nan")


def split_avg(rows, stores, dates, field, product=None):
    inside, outside = [], []
    for r in rows:
        if r["store_id"] not in stores:
            continue
        if product and r["product"] != product:
            continue
        (inside if r["date"] in dates else outside).append(float(r[field]))
    return avg(inside), avg(outside)


rain = causes["rain_reduces_outdoor_seating_sales"]
hol = causes["public_holiday_reduces_cbd_office_sales"]
prep = causes["prep_error_elevated_waste"]

key_rain = set(rain["dates"])
data_rain = {w["date"] for w in weather if float(w["precipitation_mm"]) > 5.0}
print("1. Rain dates: key", len(key_rain), "| weather.json", len(data_rain))
print("   in key, not in weather.json:", sorted(key_rain - data_rain)[:5])
print("   in weather.json, not in key:", sorted(data_rain - key_rain)[:5])

key_hol = set(hol["dates"])
data_hol = {h["date"] for h in holidays}
print("2. Key holiday dates missing from holidays.json:", sorted(key_hol - data_hol))

a, b = split_avg(sales, set(rain["store_ids"]), key_rain, "units_sold")
print(f"3. Rain, outdoor stores, sales ratio rain/dry: {a / b:.2f}  (expect about 0.70)")
a, b = split_avg(waste, set(rain["store_ids"]), key_rain, "units_wasted")
print(f"   Rain, outdoor stores, waste ratio rain/dry: {a / b:.2f}  (expect above 1)")

a, b = split_avg(sales, set(hol["store_ids"]), key_hol, "units_sold")
print(f"4. Holidays, CBD stores, sales ratio holiday/normal: {a / b:.2f}  (expect about 0.60)")

pd = set(prep["dates"])
a, b = split_avg(waste, {prep["store_id"]}, pd, "units_wasted", prep["product"])
print(f"5. Prep error waste ratio week/normal: {a / b:.2f}  (expect about 3)")
a, b = split_avg(sales, {prep["store_id"]}, pd, "units_sold", prep["product"])
print(f"   Prep error sales ratio week/normal: {a / b:.2f}  (expect about 1)")

dd = set(decoy["dates"])
a, b = split_avg(sales, {decoy["store_id"]}, dd, "units_sold")
print(f"6. Decoy promo, sales ratio promo/normal: {a / b:.2f}  (expect about 1)")
a, b = split_avg(waste, {decoy["store_id"]}, dd, "units_wasted")
print(f"   Decoy promo, waste ratio promo/normal: {a / b:.2f}  (expect about 1)")