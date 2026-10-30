"""Layer 3 store tests on SQLite (always) and PostgreSQL (when TEST_DATABASE_URL is set)."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.models import Fact
from backend.app.layer3_store.repository import ClinicalStore
from tests.test_layer2 import LETTER, doc

LATER = ("Diagnosen:<BR>Art. Hypertonie<BR>Vitalparameter:<BR>Gewicht: 74 kg<BR>"
         "Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>"
         "Ramipril 10mg oral 1 0 0 0 ST<BR>Pantoprazol 40mg oral 1 0 0 0 ST<BR>")

URLS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=URLS)
def store(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path}/t.db"
    else:
        url = os.environ["TEST_DATABASE_URL"]
        eng = make_engine(url)
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    migrate(url)
    return ClinicalStore(make_engine(url))


def ingest(store, *docs):
    recs = [process_document(d, "rules") for d in docs]
    return store.ingest(recs, extract(recs))


def test_ingest_is_idempotent_and_versions_are_superseded(store):
    r1 = ingest(store, doc())
    assert len(r1.new_documents) == 1 and r1.facts_added > 10
    r2 = ingest(store, doc())
    assert r2.unchanged_documents and not r2.new_documents and r2.facts_added == 0
    changed = doc(LETTER.replace("Ramipril 5mg", "Ramipril 7,5mg"))
    r3 = ingest(store, changed)
    assert r3.superseded_documents == r1.new_documents
    meds = [f for f in store.facts("patient-syn-A", types=["medication"]) if "Ramipril" in f.label]
    assert [m.details.strength_value for m in meds] == [7.5]
    old = store.facts("patient-syn-A", types=["medication"], include_superseded=True)
    assert {m.details.strength_value for m in old if "Ramipril" in m.label} == {5, 7.5}


def test_patient_isolation_queries_and_database_constraint(store):
    ingest(store, doc(patient="patient-A"), doc(patient="patient-B", ident="other"))
    a = store.facts("patient-A")
    assert a and all(f.patient_id == "patient-A" for f in a)
    assert all(e.patient_id == "patient-A" for f in a for e in f.evidence)
    assert store.facts("patient-unknown") == []
    b_doc = store.documents("patient-B")[0]
    with store.Session() as s:
        row = s.get(Fact, a[0].fact_id)
        s.expunge(row)
    with pytest.raises(IntegrityError):
        with store.Session.begin() as s:
            s.add(Fact(**{c.name: getattr(row, c.name) for c in Fact.__table__.columns
                          if c.name not in ("fact_id", "source_id")}, fact_id="fact:x", source_id=b_doc.source_id))


def test_temporal_queries_medication_changes_and_latest_values(store):
    ingest(store, doc(), doc(LATER, ident="syn2", date="2020-09-01"))
    lists = store.medication_lists("patient-syn-A")
    assert [d.document_date for d, _ in lists] == ["2020-02-05", "2020-09-01"]
    assert store.medication_list("patient-syn-A", as_of="2020-03-01")[0].document_date == "2020-02-05"
    changes = {c["drug"]: c["change"] for c in store.compare_medication_lists(lists[0][1], lists[1][1])}
    assert changes == {"ramipril": "changed", "pantoprazole": "added", "fiktomed": "removed"}
    assert store.latest_observation("patient-syn-A", "body_weight").details.value_num == 74
    assert store.latest_observation("patient-syn-A", "body_weight", as_of="2020-06-30").details.value_num == 80
    assert [f.details.value_num for f in store.observation_series("patient-syn-A", "body_weight")] == [80, 74]


def test_lexical_search_and_review_audit(store):
    ingest(store, doc())
    hits = store.search_passages("patient-syn-A", "Perikarderguss Echo")
    assert hits and "Perikarderguss" in hits[0][0].display_text
    assert store.search_passages("patient-other", "Perikarderguss") == []
    store.upsert_review_item("patient-syn-A", "claim:1", "claim", "Ramipril 5mg", {})
    store.set_review_status("patient-syn-A", "claim:1", "accepted", "dr.test", "checked against letter")
    item = store.review_items("patient-syn-A")[0]
    assert item["status"] == "accepted" and item["history"][0]["to"] == "accepted"
    with pytest.raises(ValueError):
        store.set_review_status("patient-syn-A", "claim:1", "approved-by-ai", "x")
