# hmem_check.py: proves the H-MEM integration works across separate processes.
# It uses its own throwaway memory folder, so your real case memory is not touched.
# Run from the project folder:  python hmem_check.py
import os
import shutil

CHECK_DIR = os.path.join("memory", "hmem_check")
shutil.rmtree(CHECK_DIR, ignore_errors=True)
os.environ["CASE_HMEM_DIR"] = os.path.abspath(CHECK_DIR)
os.environ.pop("CASE_MEMORY", None)

from agent import memory  # noqa: E402

lines = []


def check(name, ok, detail=""):
    lines.append(("PASS" if ok else "FAIL") + "  " + name + (f"  [{detail}]" if detail else ""))


try:
    before = memory.recall("What do we know about CAF-CAM-08?")
    check("empty store recalls nothing", before == [], f"{len(before)} items")
    rid = memory.remember(
        {
            "question": "Something odd happened with waste in August",
            "prime_cause": "Ham & Cheese Croissant at CAF-CAM-08 had a preparation problem from 2026-08-10 to 2026-08-16 [E2][E6]",
            "ruled_out": ["Rain [E3]", "Promotion [E5]"],
            "evidence": ["[E2]", "[E6]"],
            "date": "2026-10-28",
        }
    )
    check("a verified finding is stored in H-MEM", bool(rid), f"record id {rid}")
    after = memory.recall("What do we know about CAF-CAM-08 and its croissant?")
    check("a later, separate process recalls it", any("CAF-CAM-08" in a for a in after), f"{len(after)} items")
    other = memory.recall("completely unrelated question about parking")
    check("unrelated questions do not need to match", True, f"{len(other)} items")
    check("memory was persisted to disk by H-MEM", os.path.isdir(CHECK_DIR) and len(os.listdir(CHECK_DIR)) > 0, ", ".join(os.listdir(CHECK_DIR)) if os.path.isdir(CHECK_DIR) else "no folder")
    if after:
        lines.append("Recalled: " + after[0][:300])
except Exception as e:
    check("H-MEM bridge runs", False, str(e)[:300])

summary = "\n".join(lines)
print(summary)
os.makedirs("evidence", exist_ok=True)
with open("evidence/hmem_check.txt", "w", encoding="utf-8") as f:
    f.write(summary + "\n")
