# TEMPORARY STAND-IN so the loop works end to end.
# This JSON file is NOT the Meterless H-MEM engine and does NOT satisfy the engine
# rule. It will be replaced by H-MEM. Set CASE_MEMORY=off to disable it (used by evals).
import json
import os

PATH = "memory/cases.json"


def _load():
    if not os.path.exists(PATH):
        return []
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def recall(question, k=3):
    if os.environ.get("CASE_MEMORY") == "off":
        return []
    words = {w.lower() for w in question.split() if len(w) > 3}
    items = _load()
    items.sort(key=lambda it: -len(words & set(json.dumps(it).lower().split())))
    return [json.dumps(it) for it in items[:k]]


def remember(finding):
    if os.environ.get("CASE_MEMORY") == "off":
        return
    os.makedirs("memory", exist_ok=True)
    items = _load()
    items.append(finding)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
