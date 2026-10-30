"""IBM Track 1 benchmark runner (evaluation only).

The system receives only each situation's title + description (cases/situations.md). expected.json is read
*afterwards* to score the screens. Automatic scoring is an approximation (key-term matching + source check);
the per-question evidence is written to a report for manual review. No answers are fed back into the system.

python -m backend.app.tools.run_benchmark --cases <ibm>/cases --out artifacts/benchmark
"""
import argparse
import json
import re
import time
from pathlib import Path

from backend.app.api.service import run_task
from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore


def situations(md: str) -> list[dict]:
    out = []
    for block in re.split(r"\n## ", md)[1:]:
        title, _, rest = block.partition("\n")
        desc = rest.split("\n1.")[0].strip()
        out.append({"title": re.sub(r"^\d+\.\s*", "", title.strip()), "description": desc})
    return out


def screen_text(resp) -> str:
    parts = []
    for s in resp.sections:
        parts.append(s.title)
        for c in s.claims:
            parts += [c.text, c.original_text or "", " ".join(c.flags or []), " ".join(x.quote for x in c.citations)]
    parts += [m.title + " not documented" for m in resp.missing]
    parts += [c.title + " " + c.explanation for c in resp.conflicts]
    return " ".join(parts).casefold()


def key_terms(answer: str) -> list[str]:
    terms = re.findall(r"\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s*(?:mg|kg|µg)|\d-\d-\d|T\d N\d M\d", answer)
    words = re.findall(r"\b(?:Thrombo ASS|contrast|Glucophage|Actos|Byetta|Blopress|candesartan|metformin|pioglitazone|"
                       r"exenatide|left|right|quadrantectomy|IORT|intraoperative|ductal|HER2|Ki-67|duplex|eye|blood pressure|"
                       r"amaurosis|stenosis|6\.4|not documented|No)\b", answer, re.I)
    return list(dict.fromkeys(t.strip() for t in terms + words))


ALIASES = {"contrast": ["contrast"], "quadrantectomy": ["quadrantectomy"], "her2": ["her2"], "ki-67": ["ki-67", "ki67"],
           "duplex": ["duplex"], "eye": ["eye", "ophthalmology", "augen"], "blood pressure": ["blood pressure"],
           "6.4": ["6,4", "6.4"], "µg": ["mcg", "µg"], "no": ["not documented", "no later document", "no record"],
           "not documented": ["not documented", "no later document"]}


def term_found(t: str, text: str) -> bool:
    t2 = t.casefold().replace(" ", "")
    variants = ALIASES.get(t.casefold(), [t.casefold()])
    flat = text.replace(" ", "")
    return any(v.replace(" ", "") in flat for v in variants) or t2.replace("µg", "mcg") in flat or t2.replace(".", ",") in flat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--patient", default="patient-0000-0001")
    ap.add_argument("--out", default="artifacts/benchmark")
    a = ap.parse_args()
    store = ClinicalStore(make_engine())
    sits = situations((Path(a.cases) / "situations.md").read_text())
    expected = json.loads((Path(a.cases) / "expected.json").read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, slowest, all_conflicts = [], 0.0, {}
    claims_total = claims_verified = 0
    for i, s in enumerate(sits, 1):
        request = f"{s['title']}. {s['description']}"
        t = time.perf_counter()
        resp = run_task(store, a.patient, request)
        ms = (time.perf_counter() - t) * 1000
        slowest = max(slowest, ms)
        (out / f"situation_{i}.json").write_text(resp.model_dump_json(indent=1))
        text = screen_text(resp)
        cited = {c.document_id for sec in resp.sections for cl in sec.claims for c in cl.citations}
        for sec in resp.sections:
            for cl in sec.claims:
                claims_total += 1
                claims_verified += all(c.verified for c in cl.citations) and bool(cl.citations)
        for c in resp.conflicts:
            all_conflicts[c.conflict_id] = c
        for q in [q for q in expected if q["id"].startswith(f"{i}.")]:
            terms = key_terms(q["answer"])
            found = [t for t in terms if term_found(t, text)]
            src_ok = not q["sources"] or bool(set(q["sources"]) & cited)
            ratio = len(found) / len(terms) if terms else 0
            rows.append({"id": q["id"], "question": q["question"], "expected": q["answer"], "terms": terms,
                         "found": found, "source_cited": src_ok, "auto": "pass" if ratio >= 0.6 and src_ok else "check",
                         "ms": round(ms)})
    report = {"auto_pass": sum(r["auto"] == "pass" for r in rows), "questions": len(rows),
              "slowest_ms": round(slowest), "claims": claims_total,
              "claims_with_all_citations_verified": claims_verified,
              "conflicts": [{"title": c.title, "kind": c.kind, "severity": c.severity,
                             "documents": sorted({x.document_id for x in c.citations})} for c in all_conflicts.values()],
              "rows": rows}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1, ensure_ascii=False))
    for r in rows:
        print(f"{r['id']:4} {r['auto']:5} src={'Y' if r['source_cited'] else 'N'} {len(r['found'])}/{len(r['terms'])} "
              f"missing={[t for t in r['terms'] if t not in r['found']]}")


if __name__ == "__main__":
    main()
