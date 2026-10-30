"""Run Layer 1 + Layer 2 on private data. Example:
python -m backend.app.tools.extract_layer2 --input /private/AIM-hack-track1-shipit-main.zip --show medication
"""
import argparse
import json
from pathlib import Path

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents
from backend.app.layer2_extraction.ner.gernermed import GernermedNER
from backend.app.layer2_extraction.pipeline import extract


def _fmt(f) -> str:
    a = f.assertion
    flags = [x for x, on in (("NEG", a.negated), ("POSS", a.certainty == "possible"), ("HIST", a.temporality == "historical"),
                             ("FUT", a.temporality == "future"), ("FAM", a.experiencer == "family"), ("Q", a.question)) if on]
    code = ",".join(c.code for c in f.codings)
    date = f.event_date.value if f.event_date else "-"
    return (f"{f.document_id} {f.fact_type:15} {f.label[:70]:70} | {code:8} | {'/'.join(flags) or 'AFF':9} | "
            f"event {date:10} | {f.extractor.name}{'+' + ','.join(s.name for s in f.supporting_extractors) if f.supporting_extractors else ''}"
            f" | @{f.evidence[0].original_start}:{f.evidence[0].original_end}")


def main():
    ap = argparse.ArgumentParser(description="Evidence-linked clinical fact extraction (Layer 2)")
    ap.add_argument("--input", required=True)
    ap.add_argument("--engine", choices=["auto", "medspacy", "rules"], default="auto", help="Layer 1 section engine")
    ap.add_argument("--context-engine", choices=["native", "medspacy"], default="native")
    ap.add_argument("--gernermed", choices=["auto", "off"], default="auto", help="auto = use GERNERMED_PYTHON if set")
    ap.add_argument("--llm", choices=["off", "env"], default="off", help="env = provider from LLM_PROVIDER")
    ap.add_argument("--show", default="", help="comma-separated fact types to print, or 'all'")
    ap.add_argument("--export", default="", help="private JSON export path (contains clinical text; never commit)")
    a = ap.parse_args()
    records = ingest_documents(IBMJsonAdapter(a.input).load(), engine=a.engine)
    ner = GernermedNER.from_env() if a.gernermed == "auto" else None
    llm = None
    if a.llm == "env":
        from backend.app.layer2_extraction.llm.provider import provider_from_env
        llm = provider_from_env()
    res = extract(records, context_engine=a.context_engine, ner=ner, llm=llm)
    print(json.dumps(res.run.model_dump(mode="json"), indent=2, ensure_ascii=False))
    if a.show:
        types = None if a.show == "all" else set(a.show.split(","))
        for f in sorted(res.facts, key=lambda f: (f.fact_type, f.document_id, f.evidence[0].original_start)):
            if types is None or f.fact_type in types:
                print(_fmt(f))
    if a.export:
        p = Path(a.export)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(res.model_dump_json(indent=2), encoding="utf-8")
        print(f"Private export written: {p}")


if __name__ == "__main__":
    main()
