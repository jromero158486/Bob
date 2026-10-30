"""Phase 1 ablation: rules-only vs rules+GERNERMED++ vs rules+LLM on the IBM patient documents.

Reference = IBM's pre-extracted JSON (a silver standard: evaluation only, never used for inference).
Also: exact evidence grounding, extractor identity, and GERNERMED++ medication attribute association compared
with the deterministic medication parser.

GERNERMED_PYTHON=<env>/bin/python python -m evaluation.research.phase1_extraction --patient-dir <ibm>/data/patient-0000-0001 [--llm]
"""
import argparse
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents
from backend.app.layer2_extraction.ner.gernermed import GernermedNER, associate_attributes
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer2_extraction.validation import FactProvenanceError, verify_facts
from backend.app.tools.crosscheck_ibm import _leaves

OBS_NAMES = {"BMI": "bmi", "Body-Mass-Index": "bmi", "Körpertemperatur": "body_temperature",
             "Mini Mental State Examination": "mmse", "Gewicht": "body_weight", "Größe": "body_height",
             "Blutdruck": "blood_pressure", "HbA1c": "hba1c", "Ejektionsfraktion": "lvef", "EF": "lvef",
             "Herzfrequenz": "heart_rate"}


def _prf(ours: set, ref: set) -> dict:
    tp = len(ours & ref)
    p = tp / len(ours) if ours else 0.0
    r = tp / len(ref) if ref else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "ours": len(ours), "reference": len(ref), "ours_only": sorted(map(str, ours - ref))[:15],
            "reference_only": sorted(map(str, ref - ours))[:15]}


def silver(root: Path) -> dict:
    med, dx, obs = set(), set(), set()
    for c, m in _leaves(json.loads((root / "medication.json").read_text())):
        code = (c.get("code") or {}).get("value")
        if code:
            med |= {(d, code) for d in m["documentIds"]}
    for c, m in _leaves(json.loads((root / "diagnoses.json").read_text())):
        code = (c.get("code") or {}).get("value")
        if code:
            dx |= {(d, code[:3]) for d in m["documentIds"]}
    for s in json.loads((root / "scores-all.json").read_text())["scores"]:
        if s["name"] in OBS_NAMES:
            obs |= {(d, OBS_NAMES[s["name"]]) for v in s["values"] for d in v["documentIds"]}
    return {"med": med, "dx": dx, "obs": obs}


def score(facts, records, ref) -> dict:
    med = {(f.document_id, c.code) for f in facts if f.fact_type == "medication" for c in f.codings}
    dx = {(f.document_id, c.code[:3]) for f in facts if f.fact_type == "diagnosis" and not f.assertion.negated
          for c in f.codings}
    obs = {(f.document_id, f.details.name) for f in facts if f.fact_type == "observation"
           and f.details.name in set(OBS_NAMES.values())}  # only names the reference covers
    grounded = 0
    for f in facts:
        try:
            verify_facts([f], records)
            grounded += 1
        except FactProvenanceError:
            pass
    return {"facts": len(facts), "by_type": dict(Counter(f.fact_type for f in facts)),
            "by_extractor": dict(Counter(f.extractor.name for f in facts)),
            "with_supporting_extractor": dict(Counter(s.name for f in facts for s in f.supporting_extractors)),
            "needs_review": sum(f.review_status == "needs_review" for f in facts),
            "evidence_grounded": f"{grounded}/{len(facts)}",
            "medication_doc_atc": _prf(med, ref["med"]), "diagnosis_doc_icd3_affirmed": _prf(dx, ref["dx"]),
            "observation_doc_name_mapped": _prf(obs, ref["obs"])}


def _num(text: str | None) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(m[0].replace(",", ".")) if m else None


def attribute_association(facts, records, ner: GernermedNER) -> dict:
    """Deterministic medication rows vs GERNERMED++ Drug + associated attributes on the same passage."""
    passages = {p.passage_id: p for r in records for p in r.passages}
    meds = [f for f in facts if f.fact_type == "medication" and f.extractor.name != "gernermed++"]
    pids = sorted({f.evidence[0].passage_id for f in meds})
    texts = [passages[p].display_text for p in pids]
    t0 = time.perf_counter()
    ents = dict(zip(pids, ner.annotate(texts)))
    ms = round((time.perf_counter() - t0) * 1000)
    c = Counter()
    rows = []
    for f in meds:
        d = f.details
        groups = associate_attributes(ents[f.evidence[0].passage_id])
        drug_key = d.drug_text.casefold().split()[0]
        g = next((g for g in groups if drug_key in g["drug"].casefold() or g["drug"].casefold() in d.drug_text.casefold()), None)
        c["rule_medications"] += 1
        if not g:
            rows.append({"drug": d.drug_text, "gernermed": None})
            continue
        c["drug_found_by_gernermed"] += 1
        if d.strength_value is not None:
            c["rule_has_strength"] += 1
            s = _num((g["attrs"].get("Strength") or [None])[0])
            c["strength_found"] += s is not None
            c["strength_agrees"] += s is not None and abs(s - d.strength_value) < 1e-6
        if d.schedule is not None or d.frequency_text:
            c["rule_has_frequency"] += 1
            c["frequency_found"] += bool(g["attrs"].get("Frequency") or g["attrs"].get("Dosage"))
        if d.route:
            c["rule_has_route"] += 1
            c["route_found"] += bool(g["attrs"].get("Route"))
        if d.form:
            c["rule_has_form"] += 1
            c["form_found"] += bool(g["attrs"].get("Form"))
        for k in g["attrs"]:
            c[f"gernermed_attr_{k}"] += 1
        rows.append({"drug": d.drug_text, "rule": {"strength": d.strength_value, "unit": d.strength_unit,
                                                   "route": d.route, "frequency": d.frequency_text},
                     "gernermed": g})
    return {"counts": dict(c), "ner_ms": ms, "passages": len(pids), "examples": rows[:8]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient-dir", required=True)
    ap.add_argument("--llm", action="store_true", help="also run rules+LLM (uses LLM_PROVIDER env; costs API calls)")
    ap.add_argument("--out", default="artifacts/research/phase1_extraction.json")
    a = ap.parse_args()
    root = Path(a.patient_dir)
    records = list(ingest_documents(IBMJsonAdapter(root).load(), engine="medspacy"))
    ref = silver(root)
    out = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "data": f"{root.name} ({len(records)} documents); reference = IBM pre-extracted JSON (silver)", "configs": {}}
    ner = GernermedNER.from_env()
    configs = [("rules", {}), ("rules+gernermed", {"ner": ner})]
    if a.llm:
        from backend.app.layer2_extraction.llm.provider import provider_from_env
        configs.append(("rules+llm", {"llm": provider_from_env()}))
    for name, kw in configs:
        if name == "rules+gernermed" and ner is None:
            out["configs"][name] = {"status": "unavailable", "detail": "GERNERMED_PYTHON not set"}
            continue
        t0 = time.perf_counter()
        res = extract(records, **kw)
        out["configs"][name] = {"ms": round((time.perf_counter() - t0) * 1000),
                                "components": [c.model_dump() for c in res.run.components], **score(res.facts, records, ref)}
        if name == "rules+gernermed":
            out["gernermed_attribute_association"] = attribute_association(res.facts, records, ner)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    for name, r in out["configs"].items():
        print(name, {k: r.get(k) for k in ("ms", "facts", "by_extractor", "needs_review", "evidence_grounded", "status")})
        print("   components:", [(c["name"], c["status"], c["detail"][:60]) for c in r.get("components", [])])
        for k in ("medication_doc_atc", "diagnosis_doc_icd3_affirmed", "observation_doc_name_mapped"):
            if k in r:
                print("  ", k, {x: r[k][x] for x in ("precision", "recall", "f1", "tp", "ours", "reference")})
    if "gernermed_attribute_association" in out:
        print("attributes:", out["gernermed_attribute_association"]["counts"], out["gernermed_attribute_association"]["ner_ms"], "ms")


if __name__ == "__main__":
    main()
