# diagnose_waste.py: is the planted prep error really in the data?
import csv
import statistics as st
from collections import defaultdict
from datetime import date


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


waste = read("data/waste.csv")
sales = read("data/sales.csv")

STORE, PROD = "CAF-CAM-08", "Ham & Cheese Croissant"
START, END = "2026-08-10", "2026-08-16"

# 1. The planted store and product, day by day
by_date = {
    r["date"]: float(r["units_wasted"])
    for r in waste
    if r["store_id"] == STORE and r["product"] == PROD
}
print(f"Rows for {STORE} / {PROD}: {len(by_date)}")
print("\nDaily waste, 1 to 25 Aug:")
for d in sorted(by_date):
    if "2026-08-01" <= d <= "2026-08-25":
        print(d, by_date[d], "  <== planted week" if START <= d <= END else "")
planted = [v for d, v in by_date.items() if START <= d <= END]
other = [v for d, v in by_date.items() if not START <= d <= END]
if planted and other:
    print(f"\nAverage waste, planted week: {sum(planted) / len(planted):.1f}")
    print(f"Average waste, every other day: {sum(other) / len(other):.1f}")
    print(f"Ratio: {(sum(planted) / len(planted)) / (sum(other) / len(other)):.2f}  (expect about 3)")

# 2. Overall waste rate, with no join involved
total_waste = sum(float(r["units_wasted"]) for r in waste)
total_sold = sum(float(r["units_sold"]) for r in sales)
print(f"\nOverall waste / sales: {100 * total_waste / total_sold:.1f}%  (expect roughly 8 to 12)")

# 3. The biggest weekly waste outliers anywhere in the data
weekly = defaultdict(float)
for r in waste:
    y, w, _ = date.fromisoformat(r["date"]).isocalendar()
    weekly[(r["store_id"], r["product"], y, w)] += float(r["units_wasted"])
series = defaultdict(list)
for (s, p, y, w), v in weekly.items():
    series[(s, p)].append(v)
scores = []
for (s, p, y, w), v in weekly.items():
    med = st.median(series[(s, p)])
    if med > 0:
        scores.append((v / med, s, p, y, w, v))
scores.sort(reverse=True)
print("\nBiggest weekly waste outliers (ratio to that store+product's median week):")
for ratio, s, p, y, w, v in scores[:5]:
    print(f"  {ratio:.2f}x  {s}  {p}  {y}-W{w:02d}  ({v:.0f} units)")