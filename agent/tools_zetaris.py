# Data layer: the agent's only window onto the data is SQL through Zetaris.
import json
import os
import re
import subprocess
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

REST = os.environ.get("ZETARIS_REST_URL", "").rstrip("/")
ORG = os.environ.get("ZETARIS_ORG_ID", "1")
KEY = os.environ.get("ZETARIS_API_KEY", "")
FALLBACK = os.environ.get("ZETARIS_FALLBACK_SCRIPT", "")
TIMEOUT = int(os.environ.get("ZETARIS_TIMEOUT", "120"))
MAX_ROWS = 50

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Run ONE read-only SQL SELECT against Zetaris and return the rows. "
                "Tables: cases.sales_table, cases.waste_table, cases.weather_table, "
                "cases.holidays_table. No semicolons. Prefer aggregates and LIMIT."
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "One SELECT statement"}},
                "required": ["sql"],
            },
        },
    }
]


def _clean(sql):
    s = (sql or "").strip().rstrip(";").strip()
    if ";" in s:
        raise ValueError("Send exactly one statement, with no semicolons inside it.")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("Only SELECT queries are allowed.")
    if re.search(r"(?i)\b(insert|update|delete|drop|create|alter|grant|truncate)\b", s):
        raise ValueError("Read-only: that keyword is not allowed.")
    return s


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
    r.raise_for_status()
    j = r.json()
    return j.get("headers"), j.get("data") or []


def _via_fallback(sql):
    out = subprocess.run([sys.executable, FALLBACK, sql], capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout)[-300:])
    text = out.stdout[out.stdout.index("{"):]
    j = json.loads(text)
    return j.get("headers"), j.get("data") or []


def run_sql(sql):
    try:
        sql = _clean(sql)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        if KEY:
            try:
                cols, rows = _via_rest(sql)
            except Exception:
                if not FALLBACK:
                    raise
                cols, rows = _via_fallback(sql)
        elif FALLBACK:
            cols, rows = _via_fallback(sql)
        else:
            return {"ok": False, "error": "No ZETARIS_API_KEY or ZETARIS_FALLBACK_SCRIPT set."}
    except Exception as e:
        return {"ok": False, "error": str(e)[:400]}
    return {
        "ok": True,
        "columns": cols,
        "row_count": len(rows),
        "rows": rows[:MAX_ROWS],
        "truncated": len(rows) > MAX_ROWS,
    }