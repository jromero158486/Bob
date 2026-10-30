"""IBM Track 1 benchmark runner (evaluation only).

The system receives only each situation's title + description (cases/situations.md). expected.json is read *after*
the responses are produced, for scoring. No answers are fed back into the system.

Reported per question, kept separate on purpose:
  keyword_coverage      expected key terms found anywhere on the screen (loose; the old "15/15" metric)
  exact_values          expected numbers/doses/schedules/percentages found in *supported* claims only
  evidence              expected source documents cited by supported claims (recall) + all citations integrity-valid
  unsupported           claims shown that are not "supported" (incomplete/unverified) and conflicts
  omissions             expected terms not found -> candidate clinically meaningful omissions (manual review)
New tasks (--new-tasks, private JSON kept outside the repo) are scored by the same value/evidence checks. They are
author-written, so they test generalisation beyond the 15 questions but are not an independent evaluation.

Heuristic: DATABASE_URL=... python -m backend.app.tools.run_benchmark --cases <ibm>/cases --out artifacts/bench_heuristic
Groq:      LLM_PROVIDER=openai OPENAI_BASE_URL=https://api.groq.com/openai/v1 OPENAI_MODEL=openai/gpt-oss-120b \
           OPENAI_API_KEY=... python -m backend.app.tools.run_benchmark --cases <ibm>/cases --llm --out artifacts/bench_groq
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


def _flat(s: str) -> str:
    return s.casefold().replace(" ", "").replace("µg", "mcg").replace("½", "1/2")


def screen_text(resp) -> str:
    parts = []
    for s in resp.sections:
        parts.append(s.title)
        for c in s.claims:
            parts += [c.text, c.original_text or "", " ".join(c.flags or []), " ".join(x.quote for x in c.citations)]
    parts += [m.title + " not documented" for m in resp.missing]
    parts += [c.title + " " + c.explanation for c in resp.conflicts]
    return " ".join(parts).casefold()


def supported_text(resp) -> str:
    return " ".join(c.text + " " + (c.original_text or "") + " " + " ".join(x.quote for x in c.citations)
                    for s in resp.sections for c in s.claims if c.status in ("supported", "contradicted")).casefold()


VALUE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|mg|kg|µg|mcg|mmhg|kg/m2)|\d+(?:/\d)?-\d+(?:/\d)?-\d+(?:/\d)?|\b\d{1,2}\.\d{1,2}\.\d{4}\b"
                   r"|\b\d+(?:[.,]\d+)?\b", re.I)


def expected_values(answer: str) -> list[str]:
    vals = [v.strip() for v in VALUE.findall(answer)]
    return list(dict.fromkeys(v for v in vals if not re.fullmatch(r"(19|20)\d\d", v)))


def value_found(v: str, text: str) -> bool:
    f = _flat(text)
    vv = _flat(v)
    return vv in f or vv.replace(".", ",") in f or vv.replace(",", ".") in f


def key_terms(answer: str) -> list[str]:
    words = re.findall(r"\b(?:Thrombo ASS|contrast|Glucophage|Actos|Byetta|Blopress|candesartan|metformin|pioglitazone|"
                       r"exenatide|left|right|quadrantectomy|IORT|intraoperative|ductal|HER2|Ki-67|duplex|eye|blood pressure|"
                       r"amaurosis|stenosis|not documented|No)\b", answer, re.I)
    return list(dict.fromkeys([w.strip() for w in words] + expected_values(answer)))


ALIASES = {"eye": ["eye", "ophthalmology", "augen"], "no": ["not documented", "no later document", "no record"],
           "not documented": ["not documented", "no later document"], "ki-67": ["ki-67", "ki67"]}


def term_found(t: str, text: str) -> bool:
    return any(value_found(v, text) for v in ALIASES.get(t.casefold(), [t]))


def score(resp, expected_answer: str, expected_sources: list[str]) -> dict:
    screen, sup = screen_text(resp), supported_text(resp)
    terms = key_terms(expected_answer)
    found = [t for t in terms if term_found(t, screen)]
    vals = expected_values(expected_answer)
    vals_ok = [v for v in vals if value_found(v, sup)]
    claims = [c for s in resp.sections for c in s.claims]
    cited = {x.document_id for c in claims if c.status in ("supported", "contradicted") for x in c.citations}
    src_hit = sorted(set(expected_sources) & cited)
    return {
        "keyword_coverage": {"found": len(found), "total": len(terms)},
        "exact_values": {"found": vals_ok, "missing": [v for v in vals if v not in vals_ok], "total": len(vals)},
        "evidence": {"expected_sources": expected_sources, "cited_expected": src_hit,
                     "source_recall": round(len(src_hit) / len(expected_sources), 2) if expected_sources else None,
                     "all_citations_integrity_valid": all(x.verified for c in claims for x in c.citations)},
        "unsupported": {"claims_shown": len(claims),
                        "not_supported": [c.text for c in claims if c.status in ("not_addressed", "verification_incomplete")],
                        "contradicted": sum(c.status == "contradicted" for c in claims)},
        "omissions_for_manual_review": [t for t in terms if t not in found],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--patient", default="patient-0000-0001")
    ap.add_argument("--out", default="artifacts/benchmark")
    ap.add_argument("--llm", action="store_true", help="Use LLM_PROVIDER from env for planning; fails if unavailable")
    ap.add_argument("--new-tasks", help="Private JSON list of {patient_id, request, expected_answer, sources}")
    a = ap.parse_args()
    provider = None
    if a.llm:
        from backend.app.layer2_extraction.llm.provider import provider_from_env
        provider = provider_from_env()
    store = ClinicalStore(make_engine())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    expected = json.loads((Path(a.cases) / "expected.json").read_text())
    rows, planners, times = [], set(), []
    for i, s in enumerate(situations((Path(a.cases) / "situations.md").read_text()), 1):
        t = time.perf_counter()
        resp = run_task(store, a.patient, f"{s['title']}. {s['description']}", provider)
        times.append((time.perf_counter() - t) * 1000)
        planners.add(resp.provenance.planner)
        (out / f"situation_{i}.json").write_text(resp.model_dump_json(indent=1))
        for q in [q for q in expected if q["id"].startswith(f"{i}.")]:
            rows.append({"id": q["id"], "question": q["question"], "expected": q["answer"], "planner": resp.provenance.planner,
                         **score(resp, q["answer"], q["sources"])})
    new_rows = []
    if a.new_tasks:
        for k, task in enumerate(json.loads(Path(a.new_tasks).read_text()), 1):
            t = time.perf_counter()
            resp = run_task(store, task["patient_id"], task["request"], provider)
            times.append((time.perf_counter() - t) * 1000)
            (out / f"new_task_{k}.json").write_text(resp.model_dump_json(indent=1))
            new_rows.append({"request": task["request"], "planner": resp.provenance.planner,
                             **score(resp, task["expected_answer"], task.get("sources", []))})

    def agg(rs):
        ev = sum(r["exact_values"]["total"] for r in rs)
        return {"questions": len(rs),
                "keyword_coverage_full": sum(r["keyword_coverage"]["found"] == r["keyword_coverage"]["total"] for r in rs),
                "keyword_terms": f"{sum(r['keyword_coverage']['found'] for r in rs)}/{sum(r['keyword_coverage']['total'] for r in rs)}",
                "exact_values_in_supported_claims": f"{sum(len(r['exact_values']['found']) for r in rs)}/{ev}",
                "questions_all_values_supported": sum(not r["exact_values"]["missing"] for r in rs),
                "mean_source_recall": round(sum(r["evidence"]["source_recall"] or 0 for r in rs if r["evidence"]["source_recall"] is not None)
                                            / max(1, sum(r["evidence"]["source_recall"] is not None for r in rs)), 2),
                "questions_all_citations_valid": sum(r["evidence"]["all_citations_integrity_valid"] for r in rs),
                "questions_with_omission_candidates": sum(bool(r["omissions_for_manual_review"]) for r in rs)}
    report = {"planner": sorted(planners), "benchmark": agg(rows), "new_tasks": agg(new_rows) if new_rows else None,
              "slowest_task_ms": round(max(times)), "median_task_ms": round(sorted(times)[len(times) // 2]),
              "note": "Automatic string checks only; not a clinical accuracy judgement. Lexicons were partly tuned "
                      "while inspecting these 15 questions.", "rows": rows, "new_task_rows": new_rows}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "new_task_rows")}, indent=1, ensure_ascii=False))
    for r in rows + new_rows:
        print(f"{r.get('id', 'new'):4} kw {r['keyword_coverage']['found']}/{r['keyword_coverage']['total']} "
              f"vals {len(r['exact_values']['found'])}/{r['exact_values']['total']} miss={r['exact_values']['missing']} "
              f"src={r['evidence']['source_recall']} unsup={len(r['unsupported']['not_supported'])} "
              f"omit={r['omissions_for_manual_review']}")


if __name__ == "__main__":
    main()
