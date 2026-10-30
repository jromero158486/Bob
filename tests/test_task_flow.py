"""Milestone C: request -> plan -> retrieval -> verification -> API response (synthetic data, SQLite)."""
import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.api.schemas import Citation
from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.llm.provider import LLMResponse
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer4_planner.planner import plan_task
from backend.app.layer6_verification.verify import ClaimVerifier
from tests.test_layer2 import LETTER, doc

OTHER = ("Diagnosen:<BR>Asthma bronchiale<BR>Allergien:<BR>Penicillin-Allergie (Exanthem)<BR>"
         "Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>Apixaban 5mg oral 1 0 1 0 ST<BR>")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    url = f"sqlite:///{tmp_path_factory.mktemp('db')}/api.db"
    migrate(url)
    store = ClinicalStore(make_engine(url))
    recs = [process_document(doc(), "rules"), process_document(doc(OTHER, patient="patient-syn-B", ident="b1"), "rules")]
    store.ingest(recs, extract(recs))
    return TestClient(create_app(store=store, llm=None, run_migrations=False))


def ask(client, text, pid="patient-syn-A"):
    r = client.post("/api/tasks", json={"patient_id": pid, "request": text})
    assert r.status_code == 200, r.text
    return r.json()


def all_claims(resp):
    return [c for s in resp["sections"] for c in s["claims"]]


def test_free_text_task_yields_executable_plan_and_verified_evidence(client):
    r = ask(client, "I'm an anesthesiologist preparing this patient for surgery.")
    assert r["plan"]["planner"]["name"] == "heuristic-fallback" and r["provenance"]["llm_configured"] is False
    ops = {s["operation"] for s in r["plan"]["steps"]}
    assert {"list_allergies", "list_medications", "get_observations"} <= ops
    claims = all_claims(r)
    assert claims and all(c["citations"] for c in claims)
    assert all(cit["verified"] for c in claims for cit in c["citations"])
    assert r["verification"]["not_addressed"] == 0


def test_missing_vs_documented_negative(client):
    r = ask(client, "Before iodinated contrast: what matters? Allergies, kidney function?")
    allergy = next(s for s in r["sections"] if s["operation"] == "list_allergies")
    assert allergy["outcome"] == "documented_negative"
    assert any("Kidney" in m["title"] for m in r["missing"])


def test_negated_finding_not_presented_as_present(client):
    r = ask(client, "Summarize the cardiac findings and diagnoses")
    peri = [c for c in all_claims(r) if "ericardial" in c["text"]]
    assert peri and all(c["kind"] == "documented_negative" for c in peri)


def test_patients_are_never_mixed(client):
    a = ask(client, "I'm a pharmacist. Compare medications across admissions.")
    b = ask(client, "I'm a pharmacist. Compare medications across admissions.", pid="patient-syn-B")
    texts_a = " ".join(c["text"] for c in all_claims(a))
    texts_b = " ".join(c["text"] for c in all_claims(b))
    assert "Apixaban" not in texts_a and "Ramipril" not in texts_b
    assert {cit["document_id"] for c in all_claims(b) for cit in c["citations"]} <= {"b1"}
    assert client.post("/api/tasks", json={"patient_id": "nobody", "request": "Welche Allergien?"}).status_code == 404


def test_unseen_role_and_german_request(client):
    r = ask(client, "Ich bin Logopädin. Welche Allergien sind dokumentiert?", pid="patient-syn-B")
    assert any("penicillin" in c["text"].casefold() for c in all_claims(r))


def test_incorrect_citation_is_not_verified(client):
    store = client.app.state.store
    v = ClaimVerifier(store, "patient-syn-A", "2020-12-31", [])
    good = all_claims(ask(client, "Welche Allergien sind dokumentiert?"))[0]["citations"][0]
    assert v.verify_citation(Citation(**good))
    forged = dict(good, document_id="b1")  # citation pointing into another patient's document
    assert not v.verify_citation(Citation(**forged))


def test_llm_planner_used_when_valid_and_rejected_when_invalid():
    class LLM:
        name, model = "fake", "m1"

        def __init__(self, data):
            self.data = data

        def complete_json(self, *a):
            return LLMResponse(self.data, self.name, self.model)
    good = {"task_summary": "allergy check", "as_of": None, "presentation": {"audience": "nurse", "emphasis": [], "language": "en"},
            "steps": [{"step_id": "a", "operation": "list_allergies", "title": "Allergies", "concept": "allergies"}]}
    p = plan_task("nurse: allergies?", LLM(good))
    assert p.planner.name == "llm" and p.planner.model == "fake:m1"
    bad = dict(good, steps=[{"step_id": "a", "operation": "drop_table", "title": "x", "concept": "x"}])
    p = plan_task("nurse: allergies?", LLM(bad))
    assert p.planner.name == "heuristic-fallback" and p.warnings


def test_document_endpoint_and_review_audit(client):
    d = client.get("/api/patients/patient-syn-A/documents/syn1").json()
    assert d["passages"] and d["normalized_text"]
    assert client.get("/api/patients/patient-syn-B/documents/syn1").status_code == 404
    r = client.post("/api/patients/patient-syn-A/review", json={"item_key": "claim:x", "item_type": "claim",
                                                                "status": "rejected", "reviewer": "dr.a"})
    assert r.json()["status"] == "rejected"
    assert client.get("/api/patients/patient-syn-A/review").json()[0]["history"][0]["to"] == "rejected"
