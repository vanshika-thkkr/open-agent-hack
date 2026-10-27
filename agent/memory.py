# TEMPORARY STAND-IN so the loop works end to end.
# This JSON file is NOT the Meterless H-MEM engine and does NOT satisfy the engine
# rule. In Step 8 we replace the inside of these two functions with H-MEM.
import json
import os

PATH = "memory/cases.json"


def _load():
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def recall(question, k=3):
    words = {w.lower() for w in question.split() if len(w) > 3}
    items = _load()
    items.sort(key=lambda it: -len(words & set(json.dumps(it).lower().split())))
    return [json.dumps(it) for it in items[:k]]


def remember(finding):
    os.makedirs("memory", exist_ok=True)
    items = _load()
    items.append(finding)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)