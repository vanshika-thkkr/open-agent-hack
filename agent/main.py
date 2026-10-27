# The investigation loop. Nemotron (via Nightshift) decides which SQL to run;
# Zetaris answers; every claim must cite the query behind it.
import json
import os
import sys
from datetime import datetime

from agent import llm, memory
from agent.tools_zetaris import TOOLS, run_sql

MAX_QUERIES = 8
os.makedirs("logs", exist_ok=True)
os.makedirs("cases", exist_ok=True)

SYSTEM = """You are Case Closed, a detective for cafe food waste. A manager gives you a
mystery. Investigate it like a detective: form hypotheses, test each with SQL via the
run_sql tool, and rule suspects in or out. Never state a fact you did not get from a query.

Data (all in Zetaris; join on the date column, which is text like 2026-03-14):
- cases.sales_table: date, store_id, outdoor_seating, area_type, product, units_sold, revenue, promo_flag
- cases.waste_table: date, store_id, product, units_wasted, waste_cost
- cases.weather_table: date, precipitation_mm   (real Melbourne rainfall)
- cases.holidays_table: date, holiday_name      (real public holidays)
The data is synthetic cafe data combined with real weather and holidays.

Hypotheses to consider: heavy rain (over 5 mm), public holidays, promotions (promo_flag),
and a one-off prep error (one product at one store with a waste spike while sales stay normal).
Test promotions and compare against a baseline, so false suspects get ruled out.

Rules: one SELECT per call, no semicolons, prefer aggregates and LIMIT. If a query errors,
fix it and retry. Use at most 8 queries. Cite every claim as [Q1], [Q2] (the query number
returned in each tool result).

Finish with a case file in exactly this format:
# CASE FILE
**Question:** ...
## Prime cause
## Suspects
## Ruled out
## Verdict and recommendation
"""


def log(event, **data):
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **data}
    with open("logs/run.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def extract_findings(question, final):
    try:
        msg = llm.chat(
            [
                {"role": "system", "content": "Return ONLY one JSON object. No prose, no code fences."},
                {
                    "role": "user",
                    "content": 'From this case file return {"question": "...", "prime_cause": "...", '
                    '"ruled_out": ["..."], "stores": ["..."]}.\n\n' + final,
                },
            ]
        )
        text = (msg.get("content") or "").strip()
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception:
        return {"question": question, "summary": final[:400]}


def investigate(question):
    recalled = memory.recall(question)
    log("question", question=question)
    log("memory_recall", items=recalled)

    system = SYSTEM
    if recalled:
        system += (
            "\nWhat you already know from earlier cases (re-verify with a query before relying on it):\n"
            + "\n".join("- " + r for r in recalled)
        )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    queries, nudged, final = [], False, ""

    while True:
        out_of_budget = len(queries) >= MAX_QUERIES
        if out_of_budget:
            messages.append(
                {
                    "role": "user",
                    "content": "You have used all your queries. Write the final case file now, "
                    "using only the evidence gathered, citing [Q1], [Q2].",
                }
            )
        msg = llm.chat(messages, tools=None if out_of_budget else TOOLS)
        calls = msg.get("tool_calls") or []

        if out_of_budget or not calls:
            if not queries and not nudged and not out_of_budget:
                nudged = True
                messages.append({"role": "assistant", "content": msg.get("content") or ""})
                messages.append({"role": "user", "content": "Do not answer yet. Run queries with run_sql first."})
                continue
            final = msg.get("content") or ""
            break

        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            sql = args.get("sql", "")
            result = run_sql(sql) if fn.get("name") == "run_sql" else {"ok": False, "error": "unknown tool"}
            n = len(queries) + 1
            queries.append({"n": n, "sql": sql, "ok": result.get("ok"), "rows": result.get("row_count"), "error": result.get("error")})
            log("tool_call", n=n, sql=sql, ok=result.get("ok"), row_count=result.get("row_count"), error=result.get("error"))
            payload = json.dumps({"query": f"Q{n}", **result}, default=str)[:6000]
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": payload})

    evidence = ["", "## Evidence trail (generated by code, not by the model)"]
    for q in queries:
        status = f"{q['rows']} rows" if q["ok"] else f"ERROR: {q['error']}"
        evidence.append(f"**[Q{q['n']}]** ({status})\n```sql\n{q['sql']}\n```")
    report = final + "\n" + "\n".join(evidence)

    path = f"cases/case_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    log("final", path=path, queries=len(queries))

    memory.remember(extract_findings(question, final))
    print(report)
    print(f"\nSaved: {path}")
    return report


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or input("Case question: ")
    investigate(q)