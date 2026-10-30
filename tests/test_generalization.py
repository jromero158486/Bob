"""Generalisation on synthetic patients: unseen roles/tasks, unknown drugs, missing data, temporal change, conflicts."""
import pytest

from backend.app.api.service import run_task
from backend.app.layer1_ingestion.pipeline import process_document
from backend.app.layer2_extraction.pipeline import extract
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore
from tests.test_layer2 import LETTER, doc

MED_HDR = "Applikation mo mi ab na Einheit Info<BR>"
C1 = ("Diagnosen:<BR>Diabetes mellitus Typ II<BR>Chronische Niereninsuffizienz<BR>"
      "Entlassungsmedikation:<BR>" + MED_HDR + "Zylofantin 20mg oral 1 0 0 0 ST<BR>Metoprolol 50mg oral 1 0 1 0 ST<BR>")
C2 = ("Diagnosen:<BR>Kein Diabetes mellitus.<BR>Chronische Niereninsuffizienz<BR>"
      "Entlassungsmedikation:<BR>" + MED_HDR + "Metoprolol 100mg oral 1 0 0 0 ST<BR>Metformin 500mg oral 1 0 1 0 ST<BR>")
C = "patient-syn-C"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    url = f"sqlite:///{tmp_path_factory.mktemp('gen')}/gen.db"
    migrate(url)
    s = ClinicalStore(make_engine(url))
    recs = [process_document(d, "rules") for d in (
        doc(), doc(C1, patient=C, ident="c1", date="2021-01-10"), doc(C2, patient=C, ident="c2", date="2022-03-01"))]
    s.ingest(recs, extract(recs))
    return s


def claims(r):
    return [c for s in r.sections for c in s.claims]


def assert_clean(r, pid):
    cs = claims(r)
    assert all(x.verified for c in cs for x in c.citations), "every citation must pass integrity checks"
    docs = {d.document_id for d in []}
    assert all(c.status != "not_addressed" for c in cs)
    assert {x.document_id for c in cs for x in c.citations} <= ({"c1", "c2"} if pid == C else {"syn1"}) | docs


@pytest.mark.parametrize("request_text", [
    "Ich bin Physiotherapeutin und plane eine Mobilisation. Was muss ich wissen?",
    "As the dietitian, what is relevant for nutrition counselling?",
    "Zahnarzt: geplante Extraktion – gibt es Blutverdünner oder Allergien?",
    "Social worker preparing discharge: which medications does the patient take?",
    "Radiologie: CT mit Kontrastmittel geplant. Nierenfunktion und Allergien?",
])
def test_unseen_roles_get_verified_answers(store, request_text):
    for pid in ("patient-syn-A", C):
        r = run_task(store, pid, request_text)
        assert r.plan.steps and r.sections
        assert_clean(r, pid)


def test_unknown_medication_name_is_kept_without_code(store):
    r = run_task(store, C, "Welche Medikamente nahm der Patient im Januar 2021?")
    zylo = [c for c in claims(r) if "Zylofantin" in c.text]
    assert zylo and all(not c.codes for c in zylo) and zylo[0].status == "supported"


def test_as_of_query_uses_the_list_valid_at_that_date(store):
    r = run_task(store, C, "Medication list as of 2021-06-30?")
    texts = " ".join(c.text for c in claims(r))
    assert "Zylofantin" in texts and "Metformin" not in texts and r.as_of == "2021-06-30"


def test_medication_change_across_admissions(store):
    r = run_task(store, C, "I'm a pharmacist. What changed in the medication between admissions?")
    texts = " ".join(c.text for c in claims(r) if c.kind == "change")
    assert "Metformin" in texts and "Zylofantin" in texts and "Metoprolol" in texts


def test_missing_data_is_reported_not_invented(store):
    r = run_task(store, C, "What is the latest HbA1c and LVEF?")
    assert {m.title for m in r.missing} and not any("HbA1c" in c.text for c in claims(r))


def test_temporally_conflicting_statements_are_surfaced(store):
    r = run_task(store, C, "Hat der Patient Diabetes?")
    assert any(c.kind == "presence_conflict" for c in r.conflicts)


def test_patients_stay_isolated(store):
    r = run_task(store, "patient-syn-A", "List all medications and diagnoses")
    assert not any(x in c.text for c in claims(r) for x in ("Zylofantin", "Metformin"))
    assert "Ramipril" in LETTER


def test_named_allergen_and_smoking_absent_are_reported_missing(store):
    r = run_task(store, C, "Anaesthesia: is a penicillin allergy or smoking status documented?")
    titles = {m.title for m in r.missing}
    assert "Penicillin allergy" in titles and "Smoking status" in titles
    assert not any("Penicillin" in c.text for c in claims(r))


def test_generic_lab_request_plans_laboratory_values():
    from backend.app.layer4_planner.planner import heuristic_plan
    for req in ["Oncologist: current cancer treatment plan and relevant labs", "Hausarzt: aktuelle Laborwerte"]:
        steps = [s for s in heuristic_plan(req).steps if s.concept == "labs"]
        assert steps and "hba1c" in steps[0].filters.observation_names


PAIRS = [
    ("Nephrologist: Renal check before contrast CT: eGFR, creatinine, metformin and contrast allergy (KM).",
     "Nephrologin: Nierenfunktion vor KM-CT: eGFR, Kreatinin, Metformin und KM-Allergie?"),
    ("Neurologist: TIA work-up: prior episodes of transient monocular blindness, carotid findings and antiplatelets.",
     "Neurologe: TIA-Abklärung: frühere Episoden von Amaurosis fugax, Karotisbefunde und Thrombozytenaggregationshemmung."),
    ("Endocrinologist: DM2 control: HbA1c trend, weight loss, GLP-1 agonist and osteoporosis treatment.",
     "Endokrinologe: DM-II-Einstellung: HbA1c-Verlauf, Gewichtsabnahme, GLP-1-Agonist und Osteoporosetherapie."),
]


@pytest.mark.parametrize("en,de", PAIRS)
def test_equivalent_english_and_german_requests_plan_the_same_concepts(en, de):
    from backend.app.layer4_planner.planner import heuristic_plan
    pe, pd = heuristic_plan(en), heuristic_plan(de)
    assert {s.concept for s in pe.steps} - {"free_text"} == {s.concept for s in pd.steps} - {"free_text"}
    assert pe.presentation.language == "en" and pd.presentation.language == "de"


def test_german_request_gets_german_section_titles():
    from backend.app.layer4_planner.planner import heuristic_plan
    titles = {s.title for s in heuristic_plan(PAIRS[0][1]).steps}
    assert "Nierenfunktion" in titles and "Allergien und Unverträglichkeiten" in titles
    assert "Kidney function" in {s.title for s in heuristic_plan(PAIRS[0][0]).steps}


def test_abbreviations_and_drug_classes_reach_medication_steps():
    from backend.app.layer4_planner.planner import heuristic_plan
    concepts = {s.concept for s in heuristic_plan(PAIRS[2][0]).steps}
    assert {"glucose_lowering", "bone_health", "hba1c", "weight"} <= concepts
    assert "contrast_safety" in {s.concept for s in heuristic_plan(PAIRS[0][1]).steps}
    assert "prior_episodes" in {s.concept for s in heuristic_plan(PAIRS[1][1]).steps}
