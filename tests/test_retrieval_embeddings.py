"""Phase 2: real BGE-M3 indexing + hybrid retrieval (skipped when FlagEmbedding / cached weights are absent)."""

import pytest

from backend.app.layer4_planner.contracts import PlanStep
from backend.app.layer5_retrieval.engine import Executor
from tests.test_layer2 import doc
from tests.test_layer3 import LATER, ingest, store  # noqa: F401

emb = pytest.importorskip("backend.app.layer5_retrieval.embeddings")
pytest.importorskip("FlagEmbedding")
try:
    from huggingface_hub import snapshot_download
    snapshot_download(emb.EMBED_MODEL, local_files_only=True)
except Exception:
    pytest.skip("BGE-M3 weights not cached", allow_module_level=True)


@pytest.fixture(scope="module")
def encoder():
    return emb.shared_encoder()


def _step(title, terms):
    return PlanStep.model_validate({"step_id": "s1", "title": title, "concept": "test", "operation": "search_text",
                                    "filters": {"search_terms": terms}})


def test_index_is_incremental_and_patient_isolated(store, encoder):  # noqa: F811
    ingest(store, doc(patient="patient-A"), doc(LATER, patient="patient-B", ident="other", date="2020-09-01"))
    r1 = store.index_embeddings("patient-A", encoder)
    assert r1["encoded"] > 0 and r1["model"] == "BAAI/bge-m3"
    assert store.index_embeddings("patient-A", encoder)["encoded"] == 0
    rows_a = store.embedding_rows("patient-A", encoder.name)
    assert rows_a and len(rows_a[0].dense) == 1024
    assert store.embedding_rows("patient-B", encoder.name) == []
    hits, backend = store.dense_search("patient-B", encoder.name, rows_a[0].dense)
    assert hits == [] and backend in ("pgvector", "python-cosine")


def test_english_query_retrieves_german_passage_with_hybrid(store, encoder, monkeypatch):  # noqa: F811
    ingest(store, doc(patient="patient-A"))
    store.index_embeddings("patient-A", encoder)
    latest = max(d.document_date for d in store.documents("patient-A"))
    ex = Executor(store, "patient-A", latest, retrieval="hybrid")
    step = _step("Heart ultrasound", ["cardiac ultrasound", "ejection fraction"])
    top, passages, used = ex.search_passages(step, k=3)
    assert used == "hybrid" and any(u.startswith("dense:") for u in ex.retrieval_used)
    assert "LV-Funktion" in passages[top[0]].display_text
    lex_top, _, lex_used = Executor(store, "patient-A", latest, retrieval="lexical").search_passages(step, k=3)
    assert lex_used == "lexical" and lex_top == []  # English words never occur in the German letter


def test_missing_index_falls_back_to_lexical_and_says_so(store, encoder):  # noqa: F811
    ingest(store, doc(patient="patient-A"))
    latest = max(d.document_date for d in store.documents("patient-A"))
    ex = Executor(store, "patient-A", latest, retrieval="hybrid")
    _, _, used = ex.search_passages(_step("Ramipril", ["Ramipril"]))
    assert used == "lexical" and "no BAAI/bge-m3 embeddings" in ex.retrieval_warnings[0]
