# selftest.py: checks the DATA layer against data/answer_key.json. No language model involved.
# If this passes, the evidence the agent reads is correct, whatever the model does.
# Run from the project folder with Zetaris running:  python selftest.py
import json
import os
import sys

from agent import analysis
from agent.tools_zetaris import run_sql


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rows_of(result):
    cols = [str(c).lower() for c in result.get("columns") or []]
    return [dict(zip(cols, row)) for row in result.get("rows") or []]


def main():
    with open("data/answer_key.json", encoding="utf-8") as f:
        key = json.load(f)
    causes = {c["cause"]: c for c in key["true_causes"]}
    rain_c = causes["rain_reduces_outdoor_seating_sales"]
    hol_c = causes["public_holiday_reduces_cbd_office_sales"]
    prep_c = causes["prep_error_elevated_waste"]
    decoy = key["decoy"]

    checks = []

    def check(name, ok, detail=""):
        checks.append((bool(ok), name, detail))

    results = {}
    for k, title, sql in analysis.BATTERY:
        r = run_sql(sql, max_rows=500)
        results[k] = r
        check(f"query runs: {k}", r.get("ok") and r.get("row_count", 0) > 0, r.get("error") or f"{r.get('row_count')} rows")

    # overall waste rate should be near the generator's baseline
    if results["overall"].get("ok"):
        row = rows_of(results["overall"])[0]
        rate = num(row.get("overall_waste_rate_pct"))
        check("overall waste rate is 5 to 15 percent", rate is not None and 5 <= rate <= 15, f"{rate}")

    # the biggest weekly spike should be the planted prep error
    if results["outliers"].get("ok"):
        top = rows_of(results["outliers"])[0]
        same = top.get("store_id") == prep_c["store_id"] and top.get("product") == prep_c["product"]
        check("top spike is the planted prep error", same, f"{top.get('store_id')} / {top.get('product')} ratio {top.get('ratio')}")
        check("its ratio is at least 2.5", (num(top.get("ratio")) or 0) >= 2.5, f"{top.get('ratio')}")
        dates = sorted(prep_c["dates"])
        check(
            "its first_day and last_day match the planted week",
            top.get("first_day") == dates[0] and top.get("last_day") == dates[-1],
            f"{top.get('first_day')} to {top.get('last_day')} (expected {dates[0]} to {dates[-1]})",
        )

    # rain should cut sales only at the planted outdoor stores
    if results["rain"].get("ok"):
        rows = rows_of(results["rain"])
        planted = set(rain_c["store_ids"])
        hit = [r for r in rows if r.get("store_id") in planted]
        rest = [r for r in rows if r.get("store_id") not in planted]
        check("rain: planted stores sell under 0.85x on rain days", hit and all((num(r.get("sales_rain_to_dry")) or 9) < 0.85 for r in hit),
              ", ".join(f"{r.get('store_id')}={r.get('sales_rain_to_dry')}" for r in hit))
        check("rain: other stores stay near 1.0 (above 0.9)", rest and all((num(r.get("sales_rain_to_dry")) or 0) > 0.9 for r in rest),
              ", ".join(f"{r.get('store_id')}={r.get('sales_rain_to_dry')}" for r in rest))
        check("rain: planted stores waste more on rain days", hit and all((num(r.get("waste_pct_rain")) or 0) > (num(r.get("waste_pct_dry")) or 99) for r in hit),
              ", ".join(f"{r.get('store_id')}={r.get('waste_pct_rain')} vs {r.get('waste_pct_dry')}" for r in hit))

    # holidays should cut sales only at the planted CBD stores
    if results["holiday"].get("ok"):
        rows = rows_of(results["holiday"])
        planted = set(hol_c["store_ids"])
        hit = [r for r in rows if r.get("store_id") in planted]
        rest = [r for r in rows if r.get("store_id") not in planted]
        check("holiday: planted CBD stores sell under 0.8x", hit and all((num(r.get("sales_holiday_to_normal")) or 9) < 0.8 for r in hit),
              ", ".join(f"{r.get('store_id')}={r.get('sales_holiday_to_normal')}" for r in hit))
        check("holiday: other stores stay above 0.85", rest and all((num(r.get("sales_holiday_to_normal")) or 0) > 0.85 for r in rest),
              ", ".join(f"{r.get('store_id')}={r.get('sales_holiday_to_normal')}" for r in rest))

    # the decoy promotion should show no real effect
    if results["promo"].get("ok"):
        rows = [r for r in rows_of(results["promo"]) if r.get("store_id") == decoy["store_id"]]
        by = {int(num(r.get("promo")) or 0): r for r in rows}
        if 0 in by and 1 in by:
            ratio = (num(by[1].get("avg_sales")) or 0) / (num(by[0].get("avg_sales")) or 1)
            gap = abs((num(by[1].get("waste_pct")) or 0) - (num(by[0].get("waste_pct")) or 0))
            check("decoy promo: sales ratio within 0.9 to 1.1", 0.9 <= ratio <= 1.1, f"{ratio:.2f}")
            check("decoy promo: waste rate within 2 points", gap <= 2, f"{gap:.2f} points")
            d = sorted(decoy["dates"])
            check("decoy promo: promo dates match", by[1].get("first_day") == d[0] and by[1].get("last_day") == d[-1],
                  f"{by[1].get('first_day')} to {by[1].get('last_day')}")
        else:
            check("decoy promo: store has promo and non-promo rows", False, f"found promo values {sorted(by)}")

    lines = [("PASS" if ok else "FAIL") + "  " + name + (f"  [{detail}]" if detail else "") for ok, name, detail in checks]
    summary = f"\n{sum(1 for c in checks if c[0])}/{len(checks)} checks passed"
    print("\n".join(lines) + summary)
    os.makedirs("evidence", exist_ok=True)
    with open("evidence/selftest.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + summary + "\n")
    return 0 if all(c[0] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
