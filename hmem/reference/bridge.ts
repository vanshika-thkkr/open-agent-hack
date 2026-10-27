// Case Closed bridge to the Meterless H-MEM reference implementation (Apache-2.0, unmodified).
// Python calls this script with one JSON request on stdin and reads one JSON reply on stdout.
import { HMEM } from "./src/index.ts";
import { readFileSync } from "node:fs";

const MARK = "__HMEM__";

function clean(value: unknown): unknown {
  return JSON.parse(
    JSON.stringify(value, (key, v) => {
      if (key === "embedding") return undefined;
      if (v instanceof Map) return Object.fromEntries(v);
      if (v instanceof Set) return Array.from(v);
      return v;
    }),
  );
}

function out(obj: unknown): void {
  process.stdout.write(MARK + JSON.stringify(clean(obj)) + "\n");
}

try {
  const raw = readFileSync(0, "utf8");
  const req: any = raw.trim() ? JSON.parse(raw) : {};
  const hmem = new HMEM({ actor: "case-closed", persistDir: process.env.HMEM_DIR });

  if (req.op === "remember") {
    const rec = hmem.add({
      content: String(req.content),
      type: "factual",
      layer: "working",
      tags: Array.isArray(req.tags) ? req.tags : [],
      confidence: typeof req.confidence === "number" ? req.confidence : 0.9,
      source: String(req.source),
    });
    out({ ok: true, id: rec.id, ledger: hmem.ledger.history(rec.id) });
  } else if (req.op === "recall") {
    const result = hmem.query(String(req.query ?? ""), {
      topN: typeof req.topN === "number" ? req.topN : 3,
      threshold: typeof req.threshold === "number" ? req.threshold : 0.01,
    });
    out({ ok: true, result });
  } else if (req.op === "feedback") {
    hmem.feedback(String(req.id), req.kind);
    out({ ok: true, ledger: hmem.ledger.history(String(req.id)) });
  } else if (req.op === "ledger") {
    out({ ok: true, history: hmem.ledger.history(String(req.id)) });
  } else {
    out({ ok: false, error: "unknown op" });
  }
} catch (err) {
  out({ ok: false, error: (err as Error).message });
  process.exitCode = 1;
}
