"""Evaluation only: compare Layer 2 facts with IBM's pre-extracted JSON (a candidate index, not truth).

python -m backend.app.tools.crosscheck_ibm --patient-dir /private/data/patient-0000-0001
Prints counts and IBM-side misses. Never used to create or alter facts.
"""
import argparse
import json
from pathlib import Path

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents
from backend.app.layer2_extraction.ner.gernermed import GernermedNER
from backend.app.layer2_extraction.pipeline import extract


def _leaves(node, path=()):
    vals = node.get("values") if isinstance(node, dict) else None
    if isinstance(vals, list) and vals and isinstance(vals[0], dict) and "documentIds" in vals[0]:
        for v in vals:
            yield node, v
    elif isinstance(vals, list):
        for v in vals:
            yield from _leaves(v, path + (node.get("name"),))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient-dir", required=True)
    a = ap.parse_args()
    root = Path(a.patient_dir)
    res = extract(ingest_documents(IBMJsonAdapter(root).load()), ner=GernermedNER.from_env())
    facts = res.facts
    report = {}
    # Medications: (document, ATC)
    ours = {(f.document_id, c.code) for f in facts if f.fact_type == "medication" for c in f.codings}
    ibm = set()
    for concept, mention in _leaves(json.loads((root / "medication.json").read_text())):
        code = (concept.get("code") or {}).get("value")
        for d in mention["documentIds"]:
            ibm.add((d, code))
    report["medication_doc_atc"] = {"ibm": len(ibm), "matched": len(ibm & ours), "ibm_only": sorted(map(str, ibm - ours)),
                                    "ours_only": sorted(map(str, ours - ibm))}
    # Diagnoses: (document, ICD-10 3-char category), positive-status IBM mentions vs our affirmed facts
    ours = {(f.document_id, c.code[:3]) for f in facts if f.fact_type == "diagnosis" and not f.assertion.negated for c in f.codings}
    ibm = set()
    for concept, mention in _leaves(json.loads((root / "diagnoses.json").read_text())):
        code = (concept.get("code") or {}).get("value")
        if code:
            for d in mention["documentIds"]:
                ibm.add((d, code[:3]))
    report["diagnosis_doc_icd3"] = {"ibm": len(ibm), "matched": len(ibm & ours), "ibm_only": sorted(map(str, ibm - ours)),
                                    "ours_only": sorted(map(str, ours - ibm))}
    # Measurements: (document, name) for the names we map
    name_map = {"BMI": "bmi", "Body-Mass-Index": "bmi", "Körpertemperatur": "body_temperature",
                "Mini Mental State Examination": "mmse", "Gewicht": "body_weight", "Größe": "body_height", "Blutdruck": "blood_pressure",
                "HbA1c": "hba1c", "Ejektionsfraktion": "lvef", "EF": "lvef", "BIRADS": "birads", "Herzfrequenz": "heart_rate"}
    ours = {(f.document_id, f.details.name) for f in facts if f.fact_type == "observation"}
    ibm, unmapped = set(), set()
    for s in json.loads((root / "scores-all.json").read_text())["scores"]:
        n = name_map.get(s["name"])
        if not n:
            unmapped.add(s["name"])
            continue
        for v in s["values"]:
            for d in v["documentIds"]:
                ibm.add((d, n))
    report["observation_doc_name"] = {"ibm": len(ibm), "matched": len(ibm & ours), "ibm_only": sorted(map(str, ibm - ours)),
                                      "ibm_names_not_mapped": sorted(unmapped)}
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
