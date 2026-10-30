"""Adversarial citation-integrity tests and the integrity-vs-support separation (Layer 6)."""
import pytest
from sqlalchemy import update

from backend.app.api.schemas import Citation, Claim
from backend.app.api.service import run_task
from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.models import Document
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer6_verification.verify import ClaimVerifier
from tests.test_layer2 import LETTER, doc

A, B = "patient-syn-A", "patient-syn-B"


def _ingest(store, *docs):
    recs = [process_document(d, "rules") for d in docs]
    store.ingest(recs, extract(recs))


@pytest.fixture()
def store(tmp_path):
    url = f"sqlite:///{tmp_path}/ci.db"
    migrate(url)
    s = ClinicalStore(make_engine(url))
    _ingest(s, doc(), doc(patient=B, ident="b1"))
    old_source = s.documents(A)[0].source_id
    _ingest(s, doc(LETTER.replace("Ramipril 5mg", "Ramipril 7,5mg")))  # supersedes the first version
    s.old_source = old_source
    return s


def ramipril_claim(store) -> Claim:
    r = run_task(store, A, "I'm a pharmacist. Current medication?")
    return next(c for s in r.sections for c in s.claims if "Ramipril" in c.text)


def verifier(store, pid=A):
    return ClaimVerifier(store, pid, "2099-12-31", [])


def good_citation(store) -> Citation:
    return ramipril_claim(store).citations[0]


def errors(store, cit, pid=A):
    return verifier(store, pid).citation_errors(cit)


def test_valid_citation_passes(store):
    c = good_citation(store)
    assert errors(store, c) == [] and "7,5" in c.quote + c.passage_text


def test_forged_passage_id(store):
    c = good_citation(store)
    assert "passage_not_in_source" in errors(store, c.model_copy(update={"passage_id": c.passage_id + "x"}))
    other = store.passages(B, [p.passage_id for p in store.document(B, "b1")[1]])
    b_pid = next(iter(other))
    assert "passage_not_in_source" in errors(store, c.model_copy(update={"passage_id": b_pid}))


def test_offsets_shifted_or_outside_declared_passage(store):
    c = good_citation(store)
    shifted = c.model_copy(update={"original_start": c.original_start + 2, "original_end": c.original_end + 2})
    assert errors(store, shifted)
    d, ps = store.document(A, "syn1")
    elsewhere = next(p for p in ps if p.passage_id != c.passage_id and p.original_start > c.original_end)
    moved = c.model_copy(update={"original_start": elsewhere.original_start, "original_end": elsewhere.original_end})
    assert "offsets_outside_passage" in errors(store, moved)
    assert "offsets_outside_passage" in errors(store, c.model_copy(update={"original_end": c.original_start}))


def test_modified_quote_and_passage_text(store):
    c = good_citation(store)
    assert "quote_differs_from_original_slice" in errors(store, c.model_copy(update={"quote": c.quote.replace("7,5", "75")}))
    assert "passage_text_mismatch" in errors(store, c.model_copy(update={"passage_text": c.passage_text + " 2x tgl."}))


def test_different_patient_and_document_id(store):
    c = good_citation(store)
    assert errors(store, c, pid=B) == ["different_patient"]
    assert "document_id_mismatch" in errors(store, c.model_copy(update={"document_id": "b1"}))
    assert errors(store, c.model_copy(update={"source_id": "nope"})) == ["unknown_source_version"]


def test_superseded_version_is_rejected(store):
    with store.Session() as s:
        old = s.get(Document, store.old_source)
        assert old.is_current is False
        p = next(p for p in old.passages if "Ramipril" in p.display_text)
        cit = Citation(document_id=old.document_id, document_title=old.title, document_date=old.document_date,
                       passage_id=p.passage_id, quote=p.display_text, passage_text=p.display_text,
                       original_start=p.original_start, original_end=p.original_end, source_id=old.source_id,
                       source_sha256=old.source_sha256)
    assert errors(store, cit) == ["superseded_source_version"]


def test_checksum_tampering(store):
    c = good_citation(store)
    assert "checksum_mismatch" in errors(store, c.model_copy(update={"source_sha256": "0" * 64}))
    with store.Session() as s:  # stored source altered after ingest
        doc_row = s.get(Document, c.source_id)
        s.execute(update(Document).where(Document.source_id == c.source_id)
                  .values(original_text=doc_row.original_text.replace("Ramipril", "Ramiprik")))
        s.commit()
    assert "checksum_mismatch" in errors(store, c)


def test_citation_integrity_alone_does_not_make_a_claim_supported(store):
    claim = ramipril_claim(store)
    assert claim.status == "supported" and claim.support_basis == "source_values_matched"
    altered = claim.model_copy(update={"text": claim.text.replace("7.5", "10"), "notes": [], "status": "supported"},
                               deep=True)
    v = verifier(store).verify(altered)
    assert v.citation_integrity == "valid" and v.status == "verification_incomplete"
    assert "support:claim_values_in_source:fail" in v.support_checks


def test_positive_claim_on_negated_fact_is_not_supported(store):
    r = run_task(store, A, "Summarize the cardiac findings and diagnoses")
    neg = next(c for s in r.sections for c in s.claims if c.kind == "documented_negative")
    assert neg.status == "supported" and neg.support_basis == "documented_negative"
    flipped = neg.model_copy(update={"kind": "fact", "notes": []}, deep=True)
    assert verifier(store).verify(flipped).status == "verification_incomplete"


def test_claim_with_forged_citation_is_unsupported(store):
    claim = ramipril_claim(store)
    claim.citations[0].quote = "Ramipril 10mg"
    v = verifier(store).verify(claim)
    assert v.citation_integrity == "invalid" and v.status == "not_addressed"
