# Fixed, tested-by-selftest SQL for the screening battery, plus validated builders
# for the drill-down tools. The model never has to write SQL for the standard tests.
import re

BASE_CTE = """base AS (
  SELECT s.date AS date,
         s.store_id AS store_id,
         s.product AS product,
         CASE WHEN lower(CAST(s.outdoor_seating AS STRING)) IN ('true', '1', '1.0') THEN 1 ELSE 0 END AS outdoor,
         lower(CAST(s.area_type AS STRING)) AS area_type,
         CASE WHEN lower(CAST(s.promo_flag AS STRING)) IN ('true', '1', '1.0') THEN 1 ELSE 0 END AS promo,
         CAST(s.units_sold AS DOUBLE) AS units_sold,
         CAST(x.units_wasted AS DOUBLE) AS units_wasted
  FROM cases.sales_table s
  JOIN cases.waste_table x
    ON s.date = x.date AND s.store_id = x.store_id AND s.product = x.product
)"""

RAIN_CTE = """rb AS (
  SELECT b.*, CAST(w.precipitation_mm AS DOUBLE) AS rain_mm
  FROM base b
  JOIN cases.weather_table w ON b.date = w.date
)"""

HOLIDAY_CTE = """hb AS (
  SELECT b.*, CASE WHEN h.hdate IS NULL THEN 0 ELSE 1 END AS is_holiday
  FROM base b
  LEFT JOIN (SELECT DISTINCT date AS hdate FROM cases.holidays_table) h
    ON b.date = h.hdate
)"""

Q_OVERALL = (
    "WITH " + BASE_CTE + """
SELECT ROUND(100.0 * SUM(units_wasted) / SUM(units_sold), 2) AS overall_waste_rate_pct,
       COUNT(*) AS rows_n,
       MIN(date) AS first_day,
       MAX(date) AS last_day
FROM base"""
)

Q_OUTLIERS = """WITH weekly AS (
  SELECT store_id, product, weekofyear(CAST(date AS DATE)) AS wk,
         MIN(date) AS first_day, MAX(date) AS last_day, SUM(units_wasted) AS wasted
  FROM cases.waste_table
  GROUP BY store_id, product, weekofyear(CAST(date AS DATE))
),
med AS (
  SELECT store_id, product, percentile_approx(wasted, 0.5) AS median_week
  FROM weekly
  GROUP BY store_id, product
)
SELECT w.store_id, w.product, w.first_day, w.last_day, w.wasted, m.median_week,
       ROUND(w.wasted / m.median_week, 2) AS ratio
FROM weekly w
JOIN med m ON w.store_id = m.store_id AND w.product = m.product
WHERE m.median_week > 0
ORDER BY ratio DESC
LIMIT 10"""

Q_RAIN = (
    "WITH " + BASE_CTE + ",\n" + RAIN_CTE + """
SELECT store_id,
       MAX(outdoor) AS outdoor_seating,
       MAX(area_type) AS area_type,
       SUM(CASE WHEN rain_mm > 5 THEN 1 ELSE 0 END) AS rain_rows,
       ROUND(AVG(CASE WHEN rain_mm > 5 THEN units_sold END), 2) AS avg_sales_rain,
       ROUND(AVG(CASE WHEN rain_mm <= 5 THEN units_sold END), 2) AS avg_sales_dry,
       ROUND(AVG(CASE WHEN rain_mm > 5 THEN units_sold END)
             / AVG(CASE WHEN rain_mm <= 5 THEN units_sold END), 2) AS sales_rain_to_dry,
       ROUND(100.0 * SUM(CASE WHEN rain_mm > 5 THEN units_wasted END)
             / SUM(CASE WHEN rain_mm > 5 THEN units_sold END), 2) AS waste_pct_rain,
       ROUND(100.0 * SUM(CASE WHEN rain_mm <= 5 THEN units_wasted END)
             / SUM(CASE WHEN rain_mm <= 5 THEN units_sold END), 2) AS waste_pct_dry
FROM rb
GROUP BY store_id
ORDER BY sales_rain_to_dry ASC"""
)

Q_HOLIDAY = (
    "WITH " + BASE_CTE + ",\n" + HOLIDAY_CTE + """
SELECT store_id,
       MAX(area_type) AS area_type,
       SUM(is_holiday) AS holiday_rows,
       ROUND(AVG(CASE WHEN is_holiday = 1 THEN units_sold END), 2) AS avg_sales_holiday,
       ROUND(AVG(CASE WHEN is_holiday = 0 THEN units_sold END), 2) AS avg_sales_normal,
       ROUND(AVG(CASE WHEN is_holiday = 1 THEN units_sold END)
             / AVG(CASE WHEN is_holiday = 0 THEN units_sold END), 2) AS sales_holiday_to_normal
FROM hb
GROUP BY store_id
ORDER BY sales_holiday_to_normal ASC"""
)

Q_PROMO = (
    "WITH " + BASE_CTE + """,
promo_stores AS (
  SELECT DISTINCT store_id AS pstore FROM base WHERE promo = 1
)
SELECT b.store_id,
       b.promo,
       COUNT(*) AS rows_n,
       MIN(b.date) AS first_day,
       MAX(b.date) AS last_day,
       ROUND(AVG(b.units_sold), 2) AS avg_sales,
       ROUND(100.0 * SUM(b.units_wasted) / SUM(b.units_sold), 2) AS waste_pct
FROM base b
JOIN promo_stores p ON b.store_id = p.pstore
GROUP BY b.store_id, b.promo
ORDER BY b.store_id, b.promo"""
)

# (key, title, sql). The agent runs all of these for every case.
BATTERY = [
    ("overall", "Overall waste rate and date range (sanity check)", Q_OVERALL),
    ("outliers", "Biggest weekly waste spikes versus each store+product's own median week", Q_OUTLIERS),
    ("rain", "Rain effect per store: sales and waste on rain days (over 5 mm) versus other days", Q_RAIN),
    ("holiday", "Public-holiday effect per store: sales on holidays versus normal days", Q_HOLIDAY),
    ("promo", "Promotion effect: promo days versus non-promo days for stores that ran a promotion", Q_PROMO),
]

_STORE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
_PRODUCT_RE = re.compile(r"^[A-Za-z0-9 &'\.\-]{1,60}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _store(value):
    value = str(value or "").strip()
    if not _STORE_RE.match(value):
        raise ValueError("store_id must look like CAF-CAM-08.")
    return value


def _product(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if not _PRODUCT_RE.match(value):
        raise ValueError("product contains characters that are not allowed.")
    return value.replace("'", "''")


def _date(value, label):
    value = str(value or "").strip()
    if not _DATE_RE.match(value):
        raise ValueError(f"{label} must be a date like 2026-08-10.")
    return value


def _period(start, end):
    start, end = _date(start, "start_date"), _date(end, "end_date")
    if start > end:
        raise ValueError("start_date must not be after end_date.")
    return start, end


def compare_period_sql(store_id, start_date, end_date, product=""):
    store = _store(store_id)
    start, end = _period(start_date, end_date)
    prod = _product(product)
    prod_filter = f" AND product = '{prod}'" if prod else ""
    return (
        "WITH " + BASE_CTE + f"""
SELECT period,
       COUNT(*) AS rows_n,
       ROUND(AVG(units_sold), 2) AS avg_daily_sales,
       ROUND(AVG(units_wasted), 2) AS avg_daily_waste,
       ROUND(100.0 * SUM(units_wasted) / SUM(units_sold), 2) AS waste_pct
FROM (
  SELECT CASE WHEN date >= '{start}' AND date <= '{end}' THEN 'in_period' ELSE 'outside_period' END AS period,
         units_sold, units_wasted
  FROM base
  WHERE store_id = '{store}'{prod_filter}
) t
GROUP BY period
ORDER BY period"""
    )


def daily_detail_sql(store_id, start_date, end_date, product=""):
    store = _store(store_id)
    start, end = _period(start_date, end_date)
    prod = _product(product)
    prod_filter = f" AND product = '{prod}'" if prod else ""
    return (
        "WITH " + BASE_CTE + ",\n" + RAIN_CTE + f"""
SELECT date, product, units_sold, units_wasted,
       ROUND(100.0 * units_wasted / units_sold, 1) AS waste_pct,
       rain_mm, promo
FROM rb
WHERE store_id = '{store}' AND date >= '{start}' AND date <= '{end}'{prod_filter}
ORDER BY date, product
LIMIT 40"""
    )
