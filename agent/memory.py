# Memory for Case Closed: the Meterless H-MEM engine (official Apache-2.0 reference, unmodified)
# reached through a small Node bridge (hmem/reference/bridge.ts).
#   remember(): saves a verified finding (it must cite evidence) as an H-MEM record with a source.
#   recall():   retrieves the most relevant earlier findings at the start of a new case.
# Set CASE_MEMORY=off to switch memory off (the evaluation does this for a fair test).
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_DIR = os.path.join(ROOT, "hmem", "reference")
MARK = "__HMEM__"


def _data_dir():
    return os.environ.get("CASE_HMEM_DIR") or os.path.join(ROOT, "memory", "hmem")


def _runner():
    override = os.environ.get("CASE_HMEM_RUNNER")
    if override:
        return shlex.split(override)
    local = os.path.join(BRIDGE_DIR, "node_modules", ".bin", "tsx.cmd" if os.name == "nt" else "tsx")
    if os.path.exists(local):
        return [local, "bridge.ts"]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "tsx", "bridge.ts"]
    return ["node", "bridge.ts"]


def _call(payload, timeout=180):
    if not os.path.exists(os.path.join(BRIDGE_DIR, "bridge.ts")):
        raise RuntimeError("hmem/reference/bridge.ts not found")
    env = dict(os.environ, HMEM_DIR=_data_dir())
    p = subprocess.run(
        _runner(),
        input=json.dumps(payload),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=BRIDGE_DIR,
        env=env,
        timeout=timeout,
    )
    for line in (p.stdout or "").splitlines():
        if line.startswith(MARK):
            reply = json.loads(line[len(MARK):])
            if not reply.get("ok"):
                raise RuntimeError(reply.get("error") or "H-MEM returned an error")
            return reply
    raise RuntimeError(((p.stderr or "") + (p.stdout or ""))[-300:] or "no reply from the H-MEM bridge")


def _records(node, found=None):
    """Walk any JSON shape and collect record-like dicts (they have an id and text content)."""
    found = [] if found is None else found
    if isinstance(node, dict):
        if isinstance(node.get("content"), str) and node.get("id") is not None:
            found.append(node)
            return found
        for value in node.values():
            _records(value, found)
    elif isinstance(node, list):
        for value in node:
            _records(value, found)
    return found


def recall(question, k=3):
    if os.environ.get("CASE_MEMORY") == "off":
        return []
    try:
        reply = _call({"op": "recall", "query": question, "topN": k})
    except Exception as e:
        print(f"[H-MEM unavailable: {str(e)[:200]}]", file=sys.stderr)
        return []
    seen, out = set(), []
    for rec in _records(reply.get("result")):
        rid = rec.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        conf = rec.get("confidence")
        tail = f" (H-MEM {rid}, confidence {conf}, source {rec.get('source')})"
        out.append(rec["content"] + tail)
        if len(out) >= k:
            break
    return out


def remember(finding):
    if os.environ.get("CASE_MEMORY") == "off":
        return None
    cites = finding.get("evidence") or []
    ruled = "; ".join(finding.get("ruled_out") or [])[:300]
    content = (
        f"Case '{finding.get('question', '')}' on {finding.get('date', '')}. "
        f"Verified prime cause: {finding.get('prime_cause', '')}"
    )
    if ruled:
        content += f" Ruled out: {ruled}"
    stores = sorted(set(re.findall(r"CAF-[A-Z]+-\d+", content)))
    reply = _call(
        {
            "op": "remember",
            "content": content[:900],
            "tags": ["case-closed", "verified"] + stores,
            "confidence": 0.9,
            "source": f"case-closed:{finding.get('date', '')}:evidence {','.join(cites)}",
        }
    )
    return reply.get("id")
