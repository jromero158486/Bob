"""Phase 3: VeriFact-style claim verification (synthetic German letter, SQLite, lexical evidence retrieval)."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer5_retrieval.engine import Executor
from backend.app.layer6_verification.claim_verification import (ClaimVerificationPipeline, atomize, dates,
                                                                 deterministic_check, negated, values)
from backend.app.layer6_verification.verify import ClaimVerifier
from tests.test_task_flow import OTHER
from tests.test_layer2 import doc

os.environ.setdefault("CLINICAL_API_NO_AUTOSTART", "1")


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    url = f"sqlite:///{tmp_path_factory.mktemp('db')}/v.db"
    migrate(url)
    s = ClinicalStore(make_engine(url))
    recs = [process_document(doc(), "rules"), process_document(doc(OTHER, patient="patient-syn-B", ident="b1"), "rules")]
    s.ingest(recs, extract(recs))
    return s


def pipeline(store, judge="none", pid="patient-syn-A"):
    ex = Executor(store, pid, "2020-02-05", retrieval="lexical")
    return ClaimVerificationPipeline(ex, ClaimVerifier(store, pid, "2020-02-05", []), judge)


def test_atomize_splits_sentences_clauses_and_valued_enumerations():
    t = "Gewicht 80 kg. Keine Allergien bekannt; EF 55 %. Medikation: Ramipril 5 mg, Bisoprolol 5 mg."
    assert [c.text for c in atomize(t)] == ["Gewicht 80 kg", "Keine Allergien bekannt", "EF 55 %",
                                            "Medikation: Ramipril 5 mg", "Bisoprolol 5 mg"]
    assert all(t[c.start:c.end] == c.text for c in atomize(t))


def test_deterministic_values_units_dates_negation():
    assert values("Byetta 5 mcg, HbA1c 6,4 %") == {("5", "µg"), ("6.4", "%")}
    assert dates("am 16.05.2016") == dates("16. Mai 2016") == {(2016, 5, 16)}
    assert negated("kein Anhalt für Perikarderguss") and not negated("Perikarderguss")
    d = deterministic_check("Gewicht 90 kg", "Gewicht: 80 kg")
    assert d["values"] == "fail" and d["conflicting_values"] == ["90 kg"]
    assert deterministic_check("EF 55 % im Februar 2020", "Normale LV-Funktion (EF 55%) 05.02.2020")["dates"] == "pass"
    assert deterministic_check("Gewicht 66 kg im April 2016", "Gewicht: 66 kg", "2016-04-15")["dates"] == "pass"
    assert deterministic_check("Gewicht 66 kg im Mai 2016", "Gewicht: 66 kg", "2016-04-15")["dates"] == "fail"


def test_deterministic_baseline_verdicts(store):
    res, _ = pipeline(store).run("Gewicht 80 kg. Gewicht 90 kg. Es besteht ein Perikarderguss. "
                                 "Die Patientin hat eine Penicillin-Allergie.")
    v = {r.claim.text: r for r in res}
    assert v["Gewicht 80 kg"].verdict == "supported" and not v["Gewicht 80 kg"].needs_review
    assert v["Gewicht 90 kg"].verdict == "contradicted" and v["Gewicht 90 kg"].needs_review
    assert v["Es besteht ein Perikarderguss"].verdict == "contradicted"
    # The penicillin allergy belongs to patient B: never evidence for patient A.
    pen = v["Die Patientin hat eine Penicillin-Allergie"]
    assert pen.verdict == "not_addressed" and pen.needs_review
    assert all(c.document_id == "syn1" for r in res for c, *_ in r.evidence)


def test_every_evidence_citation_passes_integrity(store):
    res, _ = pipeline(store).run("Ramipril 5 mg")
    assert res[0].evidence and all(c.verified for c, *_ in res[0].evidence)


def test_api_verify_contract(store):
    c = TestClient(create_app(store=store, llm=None, run_migrations=False))
    r = c.post("/api/verify", json={"patient_id": "patient-syn-A", "text": "Gewicht 80 kg. Gewicht 90 kg.",
                                    "judge": "none", "retrieval_mode": "lexical"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["judge_used"] == "none" and j["summary"]["supported"] == 1 and j["summary"]["contradicted"] == 1
    assert all(cl["clinically_verified"] is False for cl in j["claims"])
    assert c.post("/api/verify", json={"patient_id": "nobody", "text": "Gewicht 80 kg"}).status_code == 404
    g = c.post("/api/verify", json={"patient_id": "patient-syn-A", "text": "Gewicht 80 kg", "judge": "groq",
                                    "retrieval_mode": "lexical"}).json()
    assert g["judge_used"] == "none" and any("no LLM provider" in w for w in g["warnings"])


def test_nli_judge_never_supports_without_deterministic_agreement(store):
    pytest.importorskip("transformers")
    from backend.app.layer6_verification.nli import NLIUnavailable, shared_nli
    try:
        shared_nli()
    except NLIUnavailable as exc:
        pytest.skip(str(exc))
    res, _ = pipeline(store, "nli").run("Normale LV-Funktion mit EF 55 %. Normale LV-Funktion mit EF 35 %.")
    v = {r.claim.text: r for r in res}
    assert v["Normale LV-Funktion mit EF 55 %"].verdict == "supported"
    assert v["Normale LV-Funktion mit EF 35 %"].verdict != "supported"
    assert v["Normale LV-Funktion mit EF 55 %"].semantic["judge"] == "nli"
