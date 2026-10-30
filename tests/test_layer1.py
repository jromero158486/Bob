import hashlib
import json
from dataclasses import replace
from zipfile import ZipFile
import pytest

from backend.app.layer1_ingestion.adapters.ibm_json import IBMJsonAdapter
from backend.app.layer1_ingestion.pipeline import process_document, ingest_documents, search_passages
from backend.app.layer1_ingestion.provenance.validator import (verify_ingested, ProvenanceError,
    verify_passage_reference)
from backend.app.layer1_ingestion.provenance.bioc_export import as_bioc_collection, dumps_bioc
from backend.app.shared.contracts.evidence import SourceDocument


def mock_document(raw: str, patient="patient-test-1", ident="testing") -> SourceDocument:
    return SourceDocument(patient, ident, raw, hashlib.sha256(raw.encode()).hexdigest(),
        "synthetic.json", "test-json", "Test document", "2026-10-30", "1", "brief", "Clinic X", "visit1", {})


def test_sections_medication_rows_and_offsets():
    text = ("Diagnosen:<BR>Diabetes mellitus Typ II<BR>Allergien:<BR>Keine bekannt.<BR>"
            "Entlassungsmedikation:<BR>Applikation mo mi ab na Einheit Info<BR>"
            "Fiktomed 30mg oral 1 0 0 0 ST<BR>Beispielpräparat 10mg oral 1 0 1/2 0 ST<BR>"
            "Weiteres Procedere:<BR>Kontrolle empfohlen.")
    item = process_document(mock_document(text), engine="rules")
    types = [p.passage_type for p in item.passages]
    assert types.count("medication_row") == 2
    assert "table_header" in types
    med = next(p for p in item.passages if "Fiktomed" in p.display_text)
    assert med.section == "discharge_medication"
    assert med.raw_text == text[med.original_start:med.original_end]
    assert verify_ingested(item)["uncovered_visible_characters"] == 0
    assert verify_passage_reference(med, text)


def test_entity_unicode_source_projection_and_br_tags():
    text = "Anamnese:<br/>Außergewöhnlich &gt; 5. ÄÖÜ.<p>Weitere Zeile</p>"
    item = process_document(mock_document(text), engine="rules")
    assert any("Außergewöhnlich > 5" in p.display_text for p in item.passages)
    assert all(p.raw_text == text[p.original_start:p.original_end] for p in item.passages)
    assert verify_ingested(item)["uncovered_visible_characters"] == 0


def test_unknown_sections_are_preserved():
    item = process_document(mock_document("Neue Spezialuntersuchung:<BR>Ein Wert dokumentiert."), "rules")
    assert item.passages[0].section == "unclassified"
    assert item.passages[1].section == "unclassified"


def test_wrapped_sentence_is_joined_and_has_original_tag():
    text = "Anamnese:<BR>Die Patientin wurde aufgrund einer<BR>unklaren Beschwerde untersucht."
    item = process_document(mock_document(text), "rules")
    paragraph = next(p for p in item.passages if "unklaren" in p.display_text)
    assert "einer<BR>unklaren" in paragraph.raw_text
    assert paragraph.display_text == "Die Patientin wurde aufgrund einer unklaren Beschwerde untersucht."


def test_tampering_fails_provenance_validation():
    item = process_document(mock_document("Diagnosen:<BR>Unbekannter Befund."), "rules")
    first = item.passages[0]
    bad = replace(first, raw_text="not the real source")
    tampered = replace(item, passages=(bad,) + item.passages[1:])
    with pytest.raises(ProvenanceError):
        verify_ingested(tampered)


def test_multiple_patients_have_separate_ids():
    a = mock_document("Diagnosen:<BR>A.", "patient-A")
    b = mock_document("Diagnosen:<BR>A.", "patient-B")
    items = ingest_documents([a, b], "rules")
    assert items[0].passages[0].passage_id != items[1].passages[0].passage_id
    assert len(search_passages(items, "Diagnosen")) == 2


def test_bioc_export_uses_raw_offsets():
    item = process_document(mock_document("Labor:<BR>Hb: 12 g/dl"), "rules")
    payload = as_bioc_collection([item])
    passage = payload["documents"][0]["passages"][1]
    assert passage["text"] == "Hb: 12 g/dl"
    assert passage["offset"] == item.passages[1].original_start
    assert json.loads(dumps_bioc([item]))["documents"][0]["id"] == item.document.source_id


def test_directory_and_zip_adapters(tmp_path):
    source = tmp_path / "root" / "patient-xyz" / "documents"
    source.mkdir(parents=True)
    doc = {"metadata": {"id": "doc1", "date": "2026-01-01", "version": "2", "title": "Demo"},
           "text": "Diagnosen:<BR>Fiktiver Befund."}
    blob = json.dumps(doc).encode()
    (source / "doc1.json").write_bytes(blob)
    zipped = tmp_path / "case.zip"
    with ZipFile(zipped, "w") as z:
        z.writestr("dataset/patient-xyz/documents/doc1.json", blob)
    direct = list(IBMJsonAdapter(source).load())
    fromzip = list(IBMJsonAdapter(zipped).load())
    assert direct[0].patient_id == fromzip[0].patient_id == "patient-xyz"
    assert fromzip[0].source_hash == direct[0].source_hash
    assert fromzip[0].document_version == "2"


def test_strict_medspacy_mode_requires_package_or_runs():
    import importlib.util
    source = mock_document("Diagnosen:<BR>Fiktiv")
    if importlib.util.find_spec("medspacy") is None:
        with pytest.raises(RuntimeError):
            process_document(source, "medspacy")
    else:
        assert process_document(source, "medspacy").section_engine == "medspacy"


def test_source_namespace_isolates_hospitals():
    a = mock_document("Befund:\nTest.", patient="patient-9")
    b = replace(a, source_namespace="other-hospital")
    assert process_document(a, "rules").document.source_id != process_document(b, "rules").document.source_id


def test_adapter_rejects_unidentified_patient(tmp_path):
    source = tmp_path / "documents"
    source.mkdir()
    (source / "doc.json").write_text(json.dumps({"text": "Test", "metadata": {"id": "doc"}}))
    with pytest.raises(ValueError, match="Missing patient identity"):
        list(IBMJsonAdapter(source).load())


def test_100_synthetic_patients_are_indexed_without_data_leakage():
    documents = [mock_document("Diagnosen:<BR>Fiktive Beobachtung.\nNeu!", patient=f"patient-{i:04d}")
                 for i in range(100)]
    items = ingest_documents(documents, engine="rules")
    assert len(items) == 100
    assert len({p.passage_id for item in items for p in item.passages}) == sum(len(item.passages) for item in items)
    assert all(verify_ingested(item)["uncovered_visible_characters"] == 0 for item in items)
