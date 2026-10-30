# Layer 2 — Clinical extraction & normalization (Milestone A)

Input: Layer 1 `IngestedDocument` / `EvidencePassage`. Output: `ExtractionResult` = `ExtractionRun` (components,
versions, resource checksums) + `ClinicalFact` candidates (`backend/app/layer2_extraction/contracts.py`, Pydantic v2).

A fact is a statement found in the source text, not a verified clinical truth. Every fact has >= 1 `EvidenceSpan`
(mention, value, context trigger) whose `raw_text == original_text[original_start:original_end]`, version-locked by
the source SHA-256. `validation.verify_facts` checks this, plus patient identity and passage containment, on every run.

## Components

| Component | What runs | Status |
|---|---|---|
| Medication table parser | Deterministic row parser: name, strength, form, route, mo-mi-ab-na schedule, frequency, unit; unknown drugs kept uncoded | ran |
| Narrative medication | Lexicon-anchored mention + strength/schedule/"morgens"; statement = started/changed/administered | ran |
| Observations | Vitals, BP (incl. 24h means/peaks), HR ranges, LVEF, HbA1c, Ki-67, ER/PR/HER2, Allred, TNM, BI-RADS, stenosis %, lesion size; generic `Name: value unit` fallback | ran |
| Diagnoses | Diagnosis-section list items (coded or uncoded) + narrative lexicon mentions; laterality from the local clause | ran |
| Allergies | Allergy section items (incl. documented "keine") + inline `X-Allergie` mentions with reactions | ran |
| Procedures | Lexicon mentions; status (performed/planned/recommended/historical/mentioned) from ConText + plan section + event date after document date | ran |
| Recommendations | Plan/follow-up sentences; due date absolute or relative ("in 2 Monaten" → document date + 2 months, precision month) | ran |
| Encounter events, demographics | Admission/discharge/visit/sample dates (malformed dates kept, `date_valid=false`, needs_review); birth date, stated age | ran |
| German NegEx/ConText | `context.py`, rules in `resources/context_rules_de.json`: negation, possible, historical, hypothetical/future, family, question prefix; abbreviation-aware clause scopes | ran (native, default) |
| medSpaCy ConText | Same rules loaded into `medspacy_context` | optional; drops abbreviation triggers (`Vd.a.`, `St.p.`, `Z.n.`) because its regex matches must align with spaCy tokens → not default |
| GERNERMED++ | Isolated subprocess (`ner/gernermed.py`, `ner/gernermed_worker.py`); Drug entities corroborate rule medications; a model-only candidate is kept only with an adjacent Strength/Dosage/Frequency entity and is `needs_review` | ran (GottBERT 1.0.0, spaCy 3.2.3) when `GERNERMED_PYTHON` is set |
| LLM structured extraction | `llm/provider.py` (OpenAI-compatible, Ollama, none) + `llm/structured_extraction.py`: Pydantic-validated proposals, each must cite a passage and a verbatim quote, otherwise rejected; accepted proposals are `needs_review` | implemented, tested with a test double; **not run on real data (no provider configured)** |
| Terminology | Local versioned lexicons in `resources/`: ATC (WHO, curated subset), ICD-10 candidate codes (category level where unsure), LOINC only for unambiguous codes | ran |

Date fields are separate: `event_date` (with `precision` and `source`: explicit_in_passage / section_heading /
relative_to_document), `document_date`, and the run's `started_at` (processing time).

## Research components — actual integration status

| Component | Paper / implementation | Version | License | Status |
|---|---|---|---|---|
| medSpaCy Sectionizer (Layer 1) | Eyre et al. 2021, github.com/medspacy/medspacy | medspacy 1.3.1, spaCy 3.7.5 | MIT | runs; Layer 1 bug fixed (title spans were silently discarded). On the IBM data it confirms all 51 rule headings and adds none |
| ConText / NegEx | Harkema et al. 2009; Chapman et al. 2001 | own German rules `de-context-0.1` | — | native implementation runs; medSpaCy ConText optional (see above) |
| GERNERMED++ | Frei, Frei-Stuber & Kramer, J Biomed Inform 2023; huggingface.co/jfrei/de_GERNERMEDpp_GottBERT | GottBERT 1.0.0 (Slim also verified) | **unspecified** on GitHub/HF (arXiv preprint CC BY-NC-SA 4.0) — weights are downloaded locally, never redistributed; clarify before any commercial use | runs in a separate Python 3.10 env because the models pin spaCy >=3.2.3,<3.3 |
| BioC | Comeau et al. 2013 | bioc 2.1 | — | Layer 1 export only |
| SNOMED CT | — | — | requires an affiliate licence | not integrated |
| Austrian MEL procedure codes | — | — | — | not integrated |

## GERNERMED++ setup (optional)

```bash
uv venv --python 3.10 ~/models/gernermed-env
uv pip install --python ~/models/gernermed-env/bin/python "spacy==3.2.3" "spacy-transformers==1.1.5" "numpy<2"
curl -L -o ~/models/de_gernermedpp_gottbert-1.0.0-py3-none-any.whl \
  https://huggingface.co/jfrei/de_GERNERMEDpp_GottBERT/resolve/main/de_GERNERMEDpp_GottBERT-any-py3-none-any.whl
uv pip install --python ~/models/gernermed-env/bin/python ~/models/de_gernermedpp_gottbert-1.0.0-py3-none-any.whl
export GERNERMED_PYTHON=~/models/gernermed-env/bin/python GERNERMED_MODEL=de_GERNERMEDpp_GottBERT
```
(The HF wheel filename has no version number; rename it as above or pip/uv refuses it. ~470 MB, CPU is fine.)

## Known limitations

- Lexicons are small and hand-curated; unknown drugs in tables are still extracted (uncoded), unknown narrative
  drugs depend on GERNERMED++ or the LLM.
- ConText scopes are heuristic: e.g. "Patientin wurde im Tumorboard besprochen und … wird empfohlen" marks the tumour
  board itself as recommended. Procedure status is inferred and flagged in `notes`.
- Repeated mentions across documents are separate facts by design; merging/longitudinal reasoning is Layers 3/5.
- No contradiction detection here (Layer 6), but malformed dates and conflicting lateralities are preserved as facts.
