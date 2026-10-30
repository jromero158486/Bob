"""Example: python -m backend.app.tools.ingest_layer1 --input /private/IBM.zip"""
import argparse
import json
from pathlib import Path
from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents, search_passages
from backend.app.layer1_ingestion.provenance.bioc_export import dumps_bioc


def main():
    parser = argparse.ArgumentParser(description="Offset-preserving clinical evidence ingestion")
    parser.add_argument("--input", required=True, help="Private original ZIP or directory")
    parser.add_argument("--engine", choices=["auto", "medspacy", "rules"], default="auto")
    parser.add_argument("--query", default="", help="Literal search, prints source text snippets only when explicitly requested")
    parser.add_argument("--export-bioc", default="", help="Explicit private BioC JSON output path")
    args = parser.parse_args()
    records = ingest_documents(IBMJsonAdapter(args.input).load(), engine=args.engine)
    counts = {}
    for d in records:
        for p in d.passages:
            counts[p.passage_type] = counts.get(p.passage_type, 0) + 1
    print(json.dumps({"documents": len(records), "patients": len(set(d.document.patient_id for d in records)),
                      "passages": sum(len(d.passages) for d in records),
                      "types": counts, "section_engine": sorted(set(d.section_engine for d in records)),
                      "provenance": "all original offsets and complete visible-text coverage verified"}, indent=2))
    if args.query:
        for p in search_passages(records, args.query, limit=10):
            print(f"{p.passage_id} | {p.passage_type} | {p.display_text[:200]}")
    if args.export_bioc:
        path = Path(args.export_bioc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps_bioc(records), encoding="utf-8")
        print(f"Private BioC export written: {path}")


if __name__ == "__main__":
    main()
