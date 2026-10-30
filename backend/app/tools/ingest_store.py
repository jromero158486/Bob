"""Ingest private documents into the clinical store (Layers 1-3). Idempotent and source-aware.

DATABASE_URL=postgresql+psycopg://clinical:clinical@localhost:5432/clinical \
  python -m backend.app.tools.ingest_store --input /private/data
"""
import argparse
import json

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents
from backend.app.layer2_extraction.ner.gernermed import GernermedNER
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import database_url, make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore


def run(input_path: str, url: str | None = None, gernermed: bool = True) -> dict:
    url = url or database_url()
    migrate(url)
    records = ingest_documents(IBMJsonAdapter(input_path).load())
    result = extract(records, ner=GernermedNER.from_env() if gernermed else None)
    rep = ClinicalStore(make_engine(url)).ingest(records, result)
    return {"database": url.split("@")[-1], "documents_new": len(rep.new_documents),
            "documents_unchanged": len(rep.unchanged_documents), "documents_superseded": len(rep.superseded_documents),
            "facts_added": rep.facts_added, "components": [c.model_dump() for c in result.run.components]}


def main():
    ap = argparse.ArgumentParser(description="Ingest documents into the clinical store")
    ap.add_argument("--input", required=True)
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--no-gernermed", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.input, a.database_url, not a.no_gernermed), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
