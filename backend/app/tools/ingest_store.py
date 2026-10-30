"""Ingest private documents into the clinical store (Layers 1-3). Idempotent and source-aware.

DATABASE_URL=postgresql+psycopg://clinical:clinical@localhost:5432/clinical \
  python -m backend.app.tools.ingest_store --input /private/data
"""
import argparse
import json
import os

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import ingest_documents
from backend.app.layer2_extraction.ner.gernermed import GernermedNER
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import database_url, make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore


def run(input_path: str, url: str | None = None, gernermed: bool = True, llm: bool = False,
        section_engine: str = "auto", embeddings: bool = False) -> dict:
    url = url or database_url()
    migrate(url)
    provider = None
    if llm:  # explicit opt-in; fail loudly rather than silently falling back
        from backend.app.layer2_extraction.llm.provider import provider_from_env
        provider = provider_from_env()
    ner = GernermedNER.from_env() if gernermed else None
    if gernermed and ner is None and os.environ.get("REQUIRE_GERNERMED") == "1":
        raise SystemExit("REQUIRE_GERNERMED=1 but GERNERMED_PYTHON is not set")
    records = ingest_documents(IBMJsonAdapter(input_path).load(), engine=section_engine)
    result = extract(records, ner=ner, llm=provider)
    store = ClinicalStore(make_engine(url))
    rep = store.ingest(records, result)
    index = None
    if embeddings:  # explicit opt-in; EmbeddingsUnavailable propagates instead of a silent fallback
        from backend.app.layer5_retrieval.embeddings import shared_encoder
        enc = shared_encoder()
        index = [store.index_embeddings(pid, enc) for pid in sorted({r.document.patient_id for r in records})]
    return {"embeddings": index, "database": url.split("@")[-1], "documents_new": len(rep.new_documents),
            "documents_unchanged": len(rep.unchanged_documents), "documents_superseded": len(rep.superseded_documents),
            "facts_added": rep.facts_added, "components": [c.model_dump() for c in result.run.components]}


def main():
    ap = argparse.ArgumentParser(description="Ingest documents into the clinical store")
    ap.add_argument("--input", required=True)
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--no-gernermed", action="store_true")
    ap.add_argument("--llm", action="store_true", help="Run LLM structured extraction (LLM_PROVIDER env); fails if unset")
    ap.add_argument("--section-engine", default="auto", choices=["auto", "medspacy", "rules"])
    ap.add_argument("--embeddings", action="store_true", help="Index passages with BGE-M3 (needs the retrieval extra)")
    a = ap.parse_args()
    print(json.dumps(run(a.input, a.database_url, not a.no_gernermed, a.llm, a.section_engine, a.embeddings), indent=2,
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
