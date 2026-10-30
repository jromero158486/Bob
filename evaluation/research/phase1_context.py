"""Phase 1: German ConText/NegEx evaluation (native rules vs medSpaCy ConText with the same rules).

Gold: evaluation/research/data/context_de.jsonl (author-written synthetic sentences; defaults negated=false,
certainty=affirmed, temporality=current, experiencer=patient). Output: artifacts/research/phase1_context.json
python -m evaluation.research.phase1_context
"""
import json
import subprocess
import time
from pathlib import Path

from backend.app.layer2_extraction import context

GOLD = Path(__file__).parent / "data" / "context_de.jsonl"
ATTRS = {"negated": False, "certainty": "affirmed", "temporality": "current", "experiencer": "patient"}


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def evaluate(engine: str, rows: list[dict]) -> dict:
    t0 = time.perf_counter()
    errors, correct = [], {a: 0 for a in ATTRS}
    pos = {a: [0, 0, 0] for a in ATTRS}  # tp, fp, fn for the non-default value
    for r in rows:
        s = r["text"].index(r["target"])
        a = context.classify(r["text"], [(s, s + len(r["target"]))], engine)[0]
        for k, default in ATTRS.items():
            gold, pred = r.get(k, default), getattr(a, k)
            correct[k] += gold == pred
            if pred != default and gold == pred:
                pos[k][0] += 1
            elif pred != default:
                pos[k][1] += 1
            if gold != default and gold != pred:
                pos[k][2] += 1
            if gold != pred:
                errors.append({"text": r["text"], "target": r["target"], "attr": k, "gold": gold, "pred": pred})
    n = len(rows)
    return {"engine": engine, "n": n, "accuracy": {k: round(v / n, 3) for k, v in correct.items()},
            "non_default_prf": {k: _prf(*v) for k, v in pos.items()},
            "all_attributes_correct": n - len({(e["text"], e["target"]) for e in errors}),
            "ms_total": round((time.perf_counter() - t0) * 1000), "errors": errors}


def main(gold: Path = GOLD):
    rows = [json.loads(line) for line in gold.read_text().splitlines() if line.strip()]
    out = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "rules_version": context.rules_version(), "data": f"{gold.name} ({len(rows)} author-written sentences)",
           "results": []}
    for eng in ("native", "medspacy"):
        try:
            out["results"].append(evaluate(eng, rows))
        except ImportError as exc:
            out["results"].append({"engine": eng, "status": "unavailable", "detail": str(exc)})
    Path("artifacts/research").mkdir(parents=True, exist_ok=True)
    Path(f"artifacts/research/phase1_context_{gold.stem}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for r in out["results"]:
        print(r["engine"], {k: v for k, v in r.items() if k in ("accuracy", "all_attributes_correct", "ms_total", "status")})
        for k, v in r.get("non_default_prf", {}).items():
            print("   ", k, v)
        for e in r.get("errors", []):
            print("    ERR", e)


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else GOLD)
