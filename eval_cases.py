# eval_cases.py: runs the demo cases and scores the agent against data/answer_key.json
import os
import re
import time

os.environ["CASE_MEMORY"] = "off"

from agent.main import investigate

CASES = [
    {
        "name": "Rain hits outdoor cafes",
        "question": "Our outdoor-seating cafés seem to sell less and waste more on certain days. Find out why.",
        "checks": [
            ("names rain as a cause", ["rain", "precipitation"], 1, None),
            ("names outdoor stores", ["caf-fit-01", "caf-stk-02", "caf-bru-03"], 2, None),
        ],
    },
    {
        "name": "Holidays hit CBD cafes",
        "question": "Our CBD office cafés had some unusually quiet days this year. What explains them?",
        "checks": [
            ("names public holidays", ["holiday"], 1, None),
            ("names CBD stores", ["caf-col-04", "caf-brk-05", "caf-doc-06"], 2, None),
        ],
    },
    {
        "name": "Prep error",
        "question": "Something odd happened with waste at one café in August. Find the culprit.",
        "checks": [
            ("finds the store", ["caf-cam-08"], 1, None),
            ("finds the product", ["croissant"], 1, None),
            ("finds the week", ["aug", "08-1"], 1, None),
        ],
    },
    {
        "name": "Decoy promotion",
        "question": "CAF-HAW-07 ran a promotion in mid-May. Did it change sales or waste?",
        "checks": [
            ("names the store", ["caf-haw-07"], 1, None),
            ("rules the promotion out", ["promo"], 1, "ruled out"),
        ],
    },
]


def section(body, title):
    m = re.search(r"##\s*" + title + r"(.*?)(?:\n##\s|\Z)", body, re.S | re.I)
    return m.group(1) if m else ""


results = []
passed = 0
total = 0

for case in CASES:
    print("\n" + "=" * 70 + "\nCASE:", case["name"])
    try:
        report = investigate(case["question"])
    except Exception as e:
        results.append(f"{case['name']}: ERROR {e}")
        total += len(case["checks"])
        continue
    body = report.split("## Evidence trail")[0]
    for label, terms, need, where in case["checks"]:
        text = (section(body, where) if where else body).lower()
        hits = sum(1 for t in terms if t in text)
        ok = hits >= need
        total += 1
        passed += ok
        results.append(f"{'PASS' if ok else 'FAIL'}  {case['name']}: {label} ({hits} of {len(terms)} terms)")
    time.sleep(10)

summary = f"\nScore: {passed}/{total} checks passed"
os.makedirs("evidence", exist_ok=True)
with open("evidence/agent_eval.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(results) + summary + "\n")
print("\n" + "\n".join(results) + summary)