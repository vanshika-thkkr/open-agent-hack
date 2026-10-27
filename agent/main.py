# Case Closed: the investigation loop.
# 1. Code runs a fixed battery of screening queries on Zetaris (always the same, always tested).
# 2. Nemotron (through Meterless Nightshift) reads the evidence, may drill down with a few
#    validated tools, and writes the case file.
# 3. Code appends the evidence trail, so it cannot be invented by the model.
import json
import os
import re
import sys
from datetime import datetime

from agent import analysis, llm, memory
from agent.tools_zetaris import TOOLS, execute_tool, run_sql

MAX_TOOL_CALLS = 6
MAX_ROUNDS = 10

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.makedirs("logs", exist_ok=True)
os.makedirs("cases", exist_ok=True)

SYSTEM = """You are Case Closed, a detective for cafe food waste. A manager asks a question.
Code has already run a standard battery of screening tests on the data in Zetaris. Their
results are given to you as evidence labelled E1, E2, and so on. Answer the manager's
specific question from that evidence, like a detective.

Data (in Zetaris): cases.sales_table (date, store_id, outdoor_seating, area_type, product,
units_sold, revenue, promo_flag), cases.waste_table (date, store_id, product, units_wasted,
waste_cost), cases.weather_table (date, precipitation_mm), cases.holidays_table (date,
holiday_name). The cafe sales and waste data is synthetic; weather and holidays are real.

RULES
1. Use only the evidence. Every factual claim must carry a citation such as [E3]. Never invent
   numbers, dates, stores or products. Copy store ids, product names and dates exactly.
2. Judge causes by effect size, and read the evidence like this:
   - Rain: a store whose sales_rain_to_dry is well below 1 (0.7 means 30 percent lower sales
     on rain days) while other stores sit near 1 is hurt by rain. A higher waste_pct_rain than
     waste_pct_dry means unsold stock was thrown away.
   - Public holidays: sales_holiday_to_normal well below 1 at some stores (look at area_type)
     means holidays cut their sales.
   - Promotion: compare the promo = 1 and promo = 0 rows for the same store. If sales and
     waste are almost the same, the promotion had no effect, so rule it out.
   - Waste spike: the outlier table ranks each store+product's weekly waste against its own
     median week, with first_day and last_day. A ratio near 3 or more while that store's sales
     stay normal points to a preparation or handling problem, not low demand. Confirm the exact
     dates and the normal sales with compare_period.
3. If the question names a store, product or period, or the evidence is not enough, use the
   tools: compare_period, daily_detail, and run_sql only as a last resort. Use at most 6 tool
   calls. Never repeat a call. If a tool returns an error, read it and change the call.
4. Answer what was asked. Put hypotheses the evidence does not support under Ruled out, with
   the number that rules them out. Do not add speculative factors.
5. If the evidence cannot answer the question, say so plainly.

Write the final answer in exactly this format and nothing else:
# CASE FILE
**Question:** (repeat the question)
## Prime cause
## Suspects
## Ruled out
## Verdict and recommendation
"""

REQUIRED = ["prime cause", "suspects", "ruled out", "verdict"]


def log(event, **data):
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **data}
    try:
        with open("logs/run.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass


def norm(sql):
    return " ".join((sql or "").split()).lower()


def fmt_rows(columns, rows, limit=25):
    lines = [" | ".join(str(c) for c in (columns or []))]
    for row in rows[:limit]:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    return "\n".join(lines)


def add_evidence(evidence, title, sql, result, tool="battery", args=None):
    item = {
        "id": f"E{len(evidence) + 1}",
        "title": title,
        "tool": tool,
        "args": args or {},
        "sql": sql,
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "columns": result.get("columns") or [],
        "rows": result.get("rows") or [],
        "row_count": result.get("row_count", 0),
    }
    evidence.append(item)
    log(
        "evidence",
        id=item["id"],
        tool=tool,
        title=title,
        ok=item["ok"],
        row_count=item["row_count"],
        error=item["error"],
    )
    return item


def packet(items):
    parts = []
    for e in items:
        if e["ok"]:
            parts.append(f"[{e['id']}] {e['title']}\n" + fmt_rows(e["columns"], e["rows"]))
        else:
            parts.append(f"[{e['id']}] {e['title']}: FAILED ({e['error']})")
    return "\n\n".join(parts)


def run_battery(evidence):
    for _key, title, sql in analysis.BATTERY:
        add_evidence(evidence, title, sql, run_sql(sql, max_rows=60))


def well_formed(text):
    low = (text or "").lower()
    return all(h in low for h in REQUIRED)


def clean_report(text, question):
    text = (text or "").strip()
    for ch in ("\u2011", "\u2010", "\u2012", "\u2013", "\u2212"):
        text = text.replace(ch, "-")

    if "# CASE FILE" in text:
        return text[text.index("# CASE FILE"):]
    return f"# CASE FILE\n**Question:** {question}\n\n{text}"


def section(text, title):
    m = re.search(r"##\s*" + title + r"[^\n]*\n(.*?)(?=\n##\s|\Z)", text, re.S | re.I)
    return m.group(1).strip() if m else ""


def fallback_report(question, evidence, reason="The language model was unavailable."):
    lines = [
        "# CASE FILE",
        f"**Question:** {question}",
        "",
        "## Prime cause",
        f"{reason} No verdict could be written. The raw screening evidence is listed in the "
        "evidence trail below.",
        "",
        "## Suspects",
        "See the evidence trail.",
        "",
        "## Ruled out",
        "Nothing could be ruled out without the model.",
        "",
        "## Verdict and recommendation",
        "Check that Meterless Nightshift is running, then rerun this case.",
    ]
    return "\n".join(lines)


def render_evidence(evidence, full=True):
    lines = ["", "## Evidence trail (generated by code, not by the model)"]
    for e in evidence:
        status = f"{e['row_count']} rows" if e["ok"] else f"ERROR: {e['error']}"
        lines.append(f"**[{e['id']}]** {e['title']} ({status})")
        if e["args"]:
            lines.append("Arguments: " + json.dumps(e["args"]))
        if full and e["sql"]:
            lines.append("```sql\n" + e["sql"] + "\n```")
        if e["ok"] and e["rows"]:
            lines.append("First rows:\n```\n" + fmt_rows(e["columns"], e["rows"], 6 if full else 3) + "\n```")
    return "\n".join(lines)


def tool_message(call_id, payload):
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload, default=str)[:5000]}


def drill_down(messages, evidence, seen, used, call):
    fn = call.get("function") or {}
    name = fn.get("name") or ""
    call_id = call.get("id") or f"call_{used}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except Exception:
        args = {}
    if not isinstance(args, dict):
        args = {}

    sql, result = execute_tool(name, args)
    if sql and norm(sql) in seen:
        result = {"ok": False, "error": f"Duplicate: you already ran this exact call as {seen[norm(sql)]}. Use that result."}
        messages.append(tool_message(call_id, result))
        log("duplicate_call", tool=name, args=args)
        return
    title = f"Drill-down: {name}"
    item = add_evidence(evidence, title, sql, result, tool=name, args=args)
    if sql:
        seen[norm(sql)] = item["id"]
    payload = {"evidence": item["id"], **{k: v for k, v in result.items() if k != "rows"}}
    if result.get("ok"):
        payload["table"] = fmt_rows(result.get("columns"), result.get("rows") or [], 40)
    messages.append(tool_message(call_id, payload))


def investigate(question):
    recalled = memory.recall(question)
    log("question", question=question)
    log("memory_recall", items=recalled)

    evidence = []
    run_battery(evidence)
    seen = {norm(e["sql"]): e["id"] for e in evidence if e["sql"]}

    system = SYSTEM
    if recalled:
        system += (
            "\nEarlier verified findings (context only; the new evidence decides):\n"
            + "\n".join("- " + r for r in recalled)
        )
    user = f"MANAGER'S QUESTION: {question}\n\nSCREENING EVIDENCE\n\n{packet(evidence)}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    final = ""
    model_ok = True
    used = 0
    try:
        for _ in range(MAX_ROUNDS):
            budget_open = used < MAX_TOOL_CALLS
            msg = llm.chat(messages, tools=TOOLS if budget_open else None)
            calls = (msg.get("tool_calls") or []) if budget_open else []
            if not calls:
                final = msg.get("content") or ""
                if final.strip():
                    break
                messages.append({"role": "user", "content": "Write the final case file now, in the required format."})
                continue
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                used += 1
                if used > MAX_TOOL_CALLS:
                    messages.append(tool_message(call.get("id") or f"call_{used}", {"ok": False, "error": "Tool budget used up."}))
                    continue
                drill_down(messages, evidence, seen, used, call)
            if used >= MAX_TOOL_CALLS:
                messages.append({"role": "user", "content": "You have used all your tool calls. Write the final case file now, citing evidence ids."})

        for _ in range(2):
            if final.strip():
                break
            messages.append({"role": "user", "content": "Write the final case file now, using only the evidence gathered."})
            final = llm.chat(messages).get("content") or ""

        if final.strip() and not well_formed(final):
            messages.append({"role": "assistant", "content": final})
            messages.append(
                {
                    "role": "user",
                    "content": "Rewrite your answer in exactly the required format, with the sections Prime cause, "
                    "Suspects, Ruled out and Verdict and recommendation. Keep the same facts and citations; add nothing new.",
                }
            )
            final = llm.chat(messages).get("content") or final

        if not final.strip():
            model_ok = False
            final = fallback_report(question, evidence, "The language model returned no answer.")
    except llm.ModelUnavailable as e:
        model_ok = False
        log("model_unavailable", error=str(e)[:300])
        final = fallback_report(question, evidence, "The language model was unavailable.")

    report_body = clean_report(final, question)
    report = report_body + "\n" + render_evidence(evidence)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"cases/case_{stamp}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    with open(f"cases/case_{stamp}.json", "w", encoding="utf-8") as f:
        json.dump({"question": question, "model_ok": model_ok, "evidence": evidence}, f, indent=2, default=str)
    log("final", path=path, evidence=len(evidence), model_ok=model_ok)

    prime = section(report_body, "Prime cause")
    cites = sorted(set(re.findall(r"\[E\d+\]", prime)))
    if model_ok and prime and cites:
        ruled = [ln.strip("-* ").strip() for ln in section(report_body, "Ruled out").splitlines() if ln.strip()]
        try:
            memory.remember(
                {
                    "question": question,
                    "prime_cause": prime[:500],
                    "ruled_out": ruled[:6],
                    "evidence": cites,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
            )
        except Exception as e:
            log("memory_error", error=str(e)[:200])

    print(report_body + "\n" + render_evidence(evidence, full=False))
    print(f"\nFull SQL for every evidence item is saved in: {path}")
    return report


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or input("Case question: ")
    investigate(q)
