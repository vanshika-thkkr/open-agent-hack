# Data layer: the agent's only window onto the data is SQL through Zetaris.
import json
import os
import re
import subprocess
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

from agent import analysis

load_dotenv()

REST = os.environ.get("ZETARIS_REST_URL", "").rstrip("/")
ORG = os.environ.get("ZETARIS_ORG_ID", "1")
KEY = os.environ.get("ZETARIS_API_KEY", "")
FALLBACK = os.environ.get("ZETARIS_FALLBACK_SCRIPT", "")
TIMEOUT = int(os.environ.get("ZETARIS_TIMEOUT", "120"))
MODEL_ROWS = 40  # rows handed back to the model per call


class SqlRejected(Exception):
    """Zetaris understood the request but rejected the SQL (HTTP 400 or 422)."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compare_period",
            "description": (
                "Compare a store (optionally one product) inside a date range against all its other "
                "days: average daily sales, average daily waste and waste rate. Use it to confirm a "
                "spike's exact dates and to check that sales stayed normal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {"type": "string", "description": "For example CAF-CAM-08"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "product": {"type": "string", "description": "Optional exact product name"},
                },
                "required": ["store_id", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_detail",
            "description": (
                "List day-by-day rows (sales, waste, waste percent, rain in mm, promo flag) for a "
                "store in a date range. At most 40 rows, so keep the range short."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "product": {"type": "string", "description": "Optional exact product name"},
                },
                "required": ["store_id", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Last resort: run ONE read-only SELECT against Zetaris. Tables: cases.sales_table "
                "(date, store_id, outdoor_seating, area_type, product, units_sold, revenue, promo_flag), "
                "cases.waste_table (date, store_id, product, units_wasted, waste_cost), "
                "cases.weather_table (date, precipitation_mm), cases.holidays_table (date, holiday_name). "
                "No semicolons."
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "One SELECT statement"}},
                "required": ["sql"],
            },
        },
    },
]


def _clean(sql):
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise ValueError("Empty query.")
    if ";" in s:
        raise ValueError("Send exactly one statement, with no semicolons inside it.")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("Only SELECT queries are allowed.")
    if re.search(r"(?i)\b(insert|update|delete|drop|create|alter|grant|truncate)\b", s):
        raise ValueError("Read-only: that keyword is not allowed.")
    if re.search(r"[A-Za-z0-9_]SELECT\b", s):
        raise ValueError("Malformed query: two statements are glued together. Write one clean SELECT.")
    return s


def _detail(response):
    try:
        body = response.json()
        text = body.get("message") or body.get("error") or body.get("detail") or json.dumps(body)
    except Exception:
        text = response.text
    return str(text)[:300]


def _via_rest(sql):
    r = requests.post(
        REST + "/sql-editor/sqls/run",
        headers={
            "Authorization": "Bearer " + KEY,
            "X-Org-ID": ORG,
            "X-Request-ID": str(uuid.uuid4()),
        },
        json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 500},
        timeout=TIMEOUT,
    )
    if r.status_code in (400, 422):
        raise SqlRejected(f"Zetaris rejected the SQL (HTTP {r.status_code}): {_detail(r)}")
    r.raise_for_status()
    j = r.json()
    return j.get("headers") or [], j.get("data") or []


def _via_fallback(sql):
    out = subprocess.run([sys.executable, FALLBACK, sql], capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout)[-300:])
    j = json.loads(out.stdout[out.stdout.index("{"):])
    return j.get("headers") or [], j.get("data") or []


def run_sql(sql, max_rows=MODEL_ROWS):
    """Run one SELECT. Never raises: always returns a dict with ok True or False."""
    try:
        sql = _clean(sql)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    last_error = "No ZETARIS_API_KEY or ZETARIS_FALLBACK_SCRIPT is set."
    try:
        if KEY:
            for attempt in range(2):
                try:
                    cols, rows = _via_rest(sql)
                    break
                except SqlRejected:
                    raise
                except Exception as e:
                    last_error = str(e)[:300]
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    if not FALLBACK:
                        return {"ok": False, "error": last_error}
                    cols, rows = _via_fallback(sql)
        elif FALLBACK:
            cols, rows = _via_fallback(sql)
        else:
            return {"ok": False, "error": last_error}
    except SqlRejected as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

    return {
        "ok": True,
        "columns": cols,
        "row_count": len(rows),
        "rows": rows[:max_rows],
        "truncated": len(rows) > max_rows,
    }


def execute_tool(name, args):
    """Returns (sql, result). Never raises."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "compare_period":
            sql = analysis.compare_period_sql(
                args.get("store_id"), args.get("start_date"), args.get("end_date"), args.get("product", "")
            )
        elif name == "daily_detail":
            sql = analysis.daily_detail_sql(
                args.get("store_id"), args.get("start_date"), args.get("end_date"), args.get("product", "")
            )
        elif name == "run_sql":
            sql = args.get("sql", "")
        else:
            return "", {"ok": False, "error": f"Unknown tool: {name}"}
    except ValueError as e:
        return "", {"ok": False, "error": str(e)}
    return sql, run_sql(sql)
