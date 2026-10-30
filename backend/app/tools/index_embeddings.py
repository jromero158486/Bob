"""Index current passages of every patient in the store with BGE-M3 (incremental: unchanged passages are skipped).
Uses the model service if EMBEDDING_SERVICE_URL is set (waiting up to EMBEDDING_WAIT seconds for it), else local
FlagEmbedding. Failures raise; the Docker entrypoint then logs that retrieval will fall back to lexical."""
from __future__ import annotations

import argparse
import json
import os

from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer5_retrieval.embeddings import BGEM3Encoder, RemoteEncoder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    a = ap.parse_args()
    store = ClinicalStore(make_engine(a.database_url))
    url = os.environ.get("EMBEDDING_SERVICE_URL")
    enc = RemoteEncoder(url, wait=float(os.environ.get("EMBEDDING_WAIT", "900"))) if url else BGEM3Encoder()
    pids = sorted(p["patient_id"] if isinstance(p, dict) else p.patient_id for p in store.patients())
    print(json.dumps([{"patient_id": pid, **store.index_embeddings(pid, enc)} for pid in pids], indent=2))


if __name__ == "__main__":
    main()
