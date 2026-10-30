"""Layer 2 tests on fully synthetic German text (no IBM data)."""
import hashlib
import os
from pathlib import Path

import pytest

from backend.app.layer1_ingestion.pipeline import ingest_documents, process_document
from backend.app.layer2_extraction.context import classify_native
from backend.app.layer2_extraction.dates import find_dates, relative_due
from backend.app.layer2_extraction.llm.provider import LLMResponse, LLMUnavailable, provider_from_env
from backend.app.layer2_extraction.ner.gernermed import GernermedNER
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer2_extraction.validation import FactProvenanceError, verify_facts
from backend.app.shared.contracts.evidence import SourceDocument

LETTER = (
    "Aufnahme am 01/02/2020 | Entlassen am 05/02/20201<BR><BR>"
    "Diagnosen:<BR>Vd.a. Mamma-Ca re.<BR>Art. Hypertonie<BR>St.p. Hypertensiver Krise 03/2019<BR>"
    "Diabetes Mellitus Typ II<BR>Allergien:<BR>Keine bekannt.<BR>Sehr geehrte Kollegen!<BR>"
    "Anamnese:<BR>Familienanamnestisch Mammakarzinom der Mutter.<BR>"
    "Fragestellung: Vorhofflimmern?<BR>"
    "Echo: kein Anhalt für Perikarderguss, Normale LV-Funktion (EF 55%).<BR>"
    "Erhobene Befunde:<BR>Größe: 165 cm<BR>Gewicht: 80 kg<BR>BMI: 29,4<BR>RR: 150/95 mmHg<BR>"
    "Therapie und Verlauf:<BR>Es wurde eine Therapie mit Bisoprolol 5mg 1-0-0 begonnen. "
    "Eine Kontrolle in 3 Monaten wird empfohlen.<BR>"
    "Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>"
    "Ramipril 5mg oral 1 0 1/2 0 ST<BR>Fiktomed 30mg oral 0 0 1 0 ST<BR>"
)


def doc(raw=LETTER, patient="patient-syn-A", ident="syn1", date="2020-02-05") -> SourceDocument:
    return SourceDocument(patient, ident, raw, hashlib.sha256(raw.encode()).hexdigest(), "syn.json", "test-json",
                          "Synthetic letter", date, "1", "Arztbrief", "Clinic X", "enc1", {})


@pytest.fixture(scope="module")
def result():
    return extract([process_document(doc(), "rules")])


def facts_of(res, ftype):
    return [f for f in res.facts if f.fact_type == ftype]


def find(res, ftype, needle):
    hits = [f for f in facts_of(res, ftype) if needle.casefold() in f.label.casefold()]
    assert hits, f"no {ftype} containing {needle!r}: {[f.label for f in facts_of(res, ftype)]}"
    return hits[0]


def test_every_evidence_span_is_exact_original_slice(result):
    raw = LETTER
    for f in result.facts:
        for ev in f.evidence:
            assert raw[ev.original_start:ev.original_end] == ev.raw_text
            assert ev.patient_id == f.patient_id == "patient-syn-A"


def test_medication_table_rows_including_unknown_drug(result):
    ram = find(result, "medication", "Ramipril")
    assert ram.details.statement == "medication_list"
    assert ram.details.strength_value == 5 and ram.details.strength_unit == "mg"
    assert (ram.details.schedule.morning, ram.details.schedule.evening) == (1, 0.5)
    assert ram.codings[0].code == "C09AA05"
    unknown = find(result, "medication", "Fiktomed")
    assert unknown.codings == () and unknown.details.ingredient is None
    assert unknown.details.schedule.evening == 1


def test_narrative_medication_start(result):
    bis = find(result, "medication", "Bisoprolol")
    assert bis.details.statement == "started"
    assert bis.details.strength_value == 5 and bis.details.schedule.morning == 1


def test_assertions_negation_uncertainty_history_family_question(result):
    assert find(result, "diagnosis", "Mamma-Ca").assertion.certainty == "possible"
    assert find(result, "diagnosis", "Mamma-Ca").details.laterality == "right"
    assert find(result, "diagnosis", "Hypertensiver Krise").assertion.temporality == "historical"
    assert find(result, "diagnosis", "Hypertensiver Krise").event_date.value == "2019-03"
    assert find(result, "diagnosis", "Art. Hypertonie").assertion.negated is False
    assert find(result, "diagnosis", "Perikarderguss").assertion.negated is True
    q = find(result, "diagnosis", "Vorhofflimmern").assertion
    assert q.question and q.certainty == "possible"
    assert find(result, "diagnosis", "Mammakarzinom der").assertion.experiencer == "family" if any(
        "Mammakarzinom der" in f.label for f in facts_of(result, "diagnosis")) else True
    fam = [f for f in facts_of(result, "diagnosis") if f.label == "Mammakarzinom"]
    assert fam and fam[0].assertion.experiencer == "family"


def test_documented_negative_allergy_is_not_missing(result):
    allergies = facts_of(result, "allergy")
    assert len(allergies) == 1 and allergies[0].assertion.negated
    assert "Sehr geehrte" not in allergies[0].label


def test_observations_and_codes(result):
    codes = {c.code for f in facts_of(result, "observation") for c in f.codings}
    assert {"8302-2", "29463-7", "39156-5", "85354-9", "10230-1"} <= codes
    bp = find(result, "observation", "150/95")
    assert (bp.details.value_num, bp.details.value_num2) == (150, 95)
    assert find(result, "observation", "BMI").details.value_num == 29.4


def test_recommendation_relative_due_and_malformed_discharge_date(result):
    rec = find(result, "recommendation", "Kontrolle")
    assert rec.assertion.temporality == "future"
    assert rec.event_date.value == "2020-05" and rec.event_date.source == "relative_to_document"
    dis = [f for f in facts_of(result, "encounter_event") if f.details.event == "discharge"][0]
    assert dis.details.date_valid is False and dis.event_date is None and dis.review_status == "needs_review"
    adm = [f for f in facts_of(result, "encounter_event") if f.details.event == "admission"][0]
    assert adm.event_date.value == "2020-02-01" and adm.document_date == "2020-02-05"


def test_patients_cannot_share_facts():
    res = extract(ingest_documents([doc(patient="patient-A"), doc(patient="patient-B")], "rules"))
    by_patient = {}
    for f in res.facts:
        assert all(ev.patient_id == f.patient_id for ev in f.evidence)
        by_patient.setdefault(f.patient_id, set()).add(f.fact_id)
    assert set(by_patient) == {"patient-A", "patient-B"}
    assert not (by_patient["patient-A"] & by_patient["patient-B"])


def test_tampered_evidence_fails_validation(result):
    rec = process_document(doc(), "rules")
    f = result.facts[0]
    bad = f.model_copy(update={"evidence": (f.evidence[0].model_copy(update={"raw_text": "erfunden"}),)})
    with pytest.raises(FactProvenanceError):
        verify_facts([bad], [rec])
    foreign = f.model_copy(update={"patient_id": "someone-else"})
    with pytest.raises(FactProvenanceError):
        verify_facts([foreign], [rec])


def test_fact_ids_are_deterministic():
    a = extract([process_document(doc(), "rules")])
    b = extract([process_document(doc(), "rules")])
    assert sorted(f.fact_id for f in a.facts) == sorted(f.fact_id for f in b.facts)


def test_dates():
    ds = find_dates("am 12.06.201511:02 und 15/04/20156, Mammographie vom 03. April 2016, Krise 06/2015, Anfang April 2016")
    assert [(d.value, d.valid) for d in ds] == [("2015-06-12", True), (None, False), ("2016-04-03", True),
                                                ("2015-06", True), ("2016-04", True)]
    assert relative_due("Duplexsonographie in 2 Monaten", "2015-06-28")[0] == "2015-08"


def test_native_context_handles_german_abbreviation_scope():
    t = "20 SVES, keine Couplets; keine komplexen ventr. Arrhythmien;"
    i = t.index("Arrhythmien")
    assert classify_native(t, [(i, i + 11)])[0].negated
    t = "Art. Hypertonie mit Z.n. Hypertensive Krise 06/2015"
    a, b = classify_native(t, [(5, 15), (25, 43)])
    assert a.temporality == "current" and b.temporality == "historical"


class FakeLLM:
    name, model = "fake", "fake-model-1"

    def __init__(self, data):
        self.data = data

    def complete_json(self, system, user, schema, schema_name):
        return LLMResponse(self.data, self.name, self.model)


def test_llm_proposals_must_quote_source_verbatim():
    rec = process_document(doc(), "rules")
    # passage_ref indices refer to the narrative passages sent; find the Bisoprolol sentence index.
    from backend.app.layer2_extraction.llm.structured_extraction import NARRATIVE_SECTIONS
    from backend.app.layer2_extraction.passage_view import views
    narrative = [v for v in views(rec) if v.passage.passage_type == "sentence"
                 and v.passage.section in NARRATIVE_SECTIONS and len(v.text) > 40]
    idx = next(i for i, v in enumerate(narrative) if "Bisoprolol" in v.text)
    llm = FakeLLM({"facts": [
        {"passage_ref": idx, "quote": "Therapie mit Bisoprolol 5mg", "fact_type": "medication", "label": "bisoprolol"},
        {"passage_ref": idx, "quote": "Therapie mit Metoprolol 50mg", "fact_type": "medication", "label": "invented"},
        {"passage_ref": 999, "quote": "x", "fact_type": "diagnosis", "label": "bad ref"},
    ]})
    res = extract([rec], llm=llm)
    llm_facts = [f for f in res.facts if f.extractor.name.startswith("llm:")]
    assert [f.label for f in llm_facts] == ["bisoprolol"]
    assert llm_facts[0].review_status == "needs_review" and llm_facts[0].extractor.version == "fake-model-1"
    comp = next(c for c in res.run.components if c.name == "llm-structured-extraction")
    assert comp.status == "ran" and "accepted=1 rejected=2" in comp.detail


def test_llm_not_configured_fails_clearly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    with pytest.raises(LLMUnavailable):
        provider_from_env()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        provider_from_env()


def test_unavailable_gernermed_is_recorded_not_fatal():
    res = extract([process_document(doc(), "rules")], ner=GernermedNER("/nonexistent/python"))
    comp = next(c for c in res.run.components if c.name == "gernermed++")
    assert comp.status == "failed" and res.facts


@pytest.mark.skipif(not os.environ.get("GERNERMED_PYTHON"), reason="GERNERMED_PYTHON not configured")
def test_real_gernermed_supports_rule_medications():
    res = extract([process_document(doc(), "rules")], ner=GernermedNER.from_env())
    comp = next(c for c in res.run.components if c.name == "gernermed++")
    assert comp.status == "ran" and "GERNERMEDpp" in comp.version
    ram = find(res, "medication", "Ramipril")
    assert any(s.name == "gernermed++" for s in ram.supporting_extractors)


IBM = os.environ.get("CLINICAL_IBM_DATA")


@pytest.mark.skipif(not IBM, reason="CLINICAL_IBM_DATA (private IBM patient folder or ZIP) not set")
def test_private_ibm_data_structural_checks():
    from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
    records = ingest_documents(IBMJsonAdapter(Path(IBM)).load())
    assert len(records) == 8
    res = extract(records)
    assert verify_facts(res.facts, records) > 0
    med_rows = {p.passage_id for r in records for p in r.passages if p.passage_type == "medication_row"}
    covered = {ev.passage_id for f in res.facts if f.fact_type == "medication" for ev in f.evidence}
    assert med_rows <= covered, "every medication table row must yield a medication fact"


def test_medspacy_context_agrees_on_plain_negation_and_documents_abbreviation_gap():
    pytest.importorskip("medspacy")
    from backend.app.layer2_extraction.context import classify_medspacy
    t = "Sonographisch zeigen sich axillär keine vergrößerten Lymphknoten."
    i = t.index("Lymphknoten")
    assert classify_medspacy(t, [(i, i + 11)])[0].negated
    t = "St.p. Hypertensiver Krise 06/2015"
    # Known limitation: medSpaCy's regex matcher drops triggers misaligned with spaCy tokens ('St.p.').
    assert classify_native(t, [(6, 25)])[0].temporality == "historical"
