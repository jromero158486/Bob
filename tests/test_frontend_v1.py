"""Layer 7 contract for the Lovable frontend (/api/v1): live data only, exact evidence spans, patient isolation."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore
from tests.test_layer2 import doc
from tests.test_task_flow import OTHER

os.environ.setdefault("CLINICAL_API_NO_AUTOSTART", "1")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    url = f"sqlite:///{tmp_path_factory.mktemp('db')}/v1.db"
    migrate(url)
    store = ClinicalStore(make_engine(url))
    recs = [process_document(doc(), "rules"), process_document(doc(OTHER, patient="patient-syn-B", ident="b1"), "rules")]
    store.ingest(recs, extract(recs))
    return TestClient(create_app(store=store, llm=None, run_migrations=False))


def sections(client, pid):
    return {s["id"]: s["text"] for d in client.get(f"/api/v1/patients/{pid}/documents").json() for s in d["sections"]}


def test_task_result_is_live_with_exact_evidence_spans(client):
    r = client.post("/api/v1/clinical-tasks", json={"patientId": "patient-syn-A", "role": "Hausärztin",
                                                    "task": "Aktuelle Medikation und Allergien?", "locale": "de"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["origin"] == "live" and j["blocks"] and j["facts"] and "planner" in j["interpretedIntent"]
    sec = sections(client, "patient-syn-A")
    spans = [e for f in j["facts"].values() for e in f["evidence"]]
    assert spans and all(sec[e["sectionId"]][e["start"]:e["end"]] == e["quote"] for e in spans)
    texts = " ".join(f["statement"] for f in j["facts"].values())
    assert "Ramipril" in texts and "Apixaban" not in texts  # patient B's drug never leaks into A
    assert all(b["kind"] != "fact_list" or b["factIds"] for b in j["blocks"])


def test_missing_information_and_unknown_patient(client):
    j = client.post("/api/v1/clinical-tasks", json={"patientId": "patient-syn-A", "task": "Is her smoking status documented?"}).json()
    missing = [b for b in j["blocks"] if b["kind"] == "missing_information"]
    assert missing and missing[0]["items"][0]["searchedDocuments"]
    assert client.post("/api/v1/clinical-tasks", json={"patientId": "nobody", "task": "abc"}).status_code == 404
    assert client.get("/api/v1/patients/nobody").status_code == 404


def test_patients_documents_longitudinal_review_and_verify(client):
    ps = client.get("/api/v1/patients").json()
    assert {p["id"] for p in ps} == {"patient-syn-A", "patient-syn-B"}
    lg = client.get("/api/v1/patients/patient-syn-A/longitudinal").json()
    assert lg["medications"]["rows"] and lg["timeline"] and all(d["factId"] in lg["facts"] for d in lg["diagnoses"])
    items = client.get("/api/v1/patients/patient-syn-A/review-items").json()
    if items:
        assert client.post(f"/api/v1/review-items/{items[0]['id']}/decision",
                           json={"reviewItemId": items[0]["id"], "factId": items[0]["fact"]["id"], "decision": "approve"}).json() == {"accepted": True}
    v = client.post("/api/v1/verify-statement", json={"patientId": "patient-syn-A", "statement": "Gewicht 80 kg", "judge": "none"})
    assert v.status_code == 200 and v.json()["claims"][0]["clinically_verified"] is False
