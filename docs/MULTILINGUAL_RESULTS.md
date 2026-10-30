# Multilingual generalization (English ↔ German) — new clinical tasks

Goal: correct, evidence-linked answers to **new** tasks in English and German, beyond the 15 IBM questions.
Synthetic IBM patient only; the official dataset is unchanged, and no synthetic data or agent was added.
Each answer was checked by hand against the original IBM documents, not by keyword matching. Raw payloads are kept in
the git-ignored `artifacts/judging/ml*`, because the repo is public.

## Method

- 5 new tasks, each written in English and German (10 runs), with different roles. They include broad requests,
  synonyms ("transient monocular blindness" / "Amaurosis fugax"), abbreviations (KM, DM2/DM-II, GLP-1, TIA, BMI) and
  several topics per question.
- Each English/German pair is compared on: essential facts, values, dates and doses; source documents; the language of
  the UI headings; and whether missing information is distinct from documented facts.
- 6 English/German statement pairs (12 checks) go through the optional "Verify clinical statement" action
  (supported / contradicted / not documented).
- Runner: `evaluation/judging/hosted_ibm_audit.py --extra <tasks.json>`. Every evidence link is checked against the
  section offsets and the original document.
- **Before** = deployed production `8acac85`. **After** = this branch, run in a local Docker stack (production was
  not redeployed).

## Tasks (EN = English request, DE = German request)

| # | Role | English request (the German one is equivalent) |
|---|---|---|
| P1 | Anaesthetist / Anästhesist | Before general anaesthesia: anticoagulants or antiplatelets, allergies, BMI, sleep apnoea or reflux |
| P2 | Nephrologist / Nephrologin | Renal check before contrast CT: eGFR, creatinine, metformin and contrast allergy (KM) |
| P3 | Neurologist / Neurologe | TIA work-up: prior transient monocular blindness, carotid findings, current antiplatelet therapy |
| P4 | Gynaecologic oncologist / Gynäkoonkologin | Overview of the breast cancer: biopsy, hormone receptors, staging, next steps |
| P5 | Endocrinologist / Endokrinologe | DM2 control: HbA1c trend, weight loss, GLP-1 agonist and osteoporosis treatment |

## Results

| # | Before: EN | Before: DE | After: EN | After: DE | Cause of the failure |
|---|---|---|---|---|---|
| P1 | pass | facts pass, headings English | pass | pass (German headings) | language generation |
| P2 | pass | **fail**: metformin missing ("KM-CT" not recognized) | pass | pass | task planning |
| P3 | pass (unrelated oncology plans included) | **fail**: previous amaurosis fugax episode missing | pass (same extra content) | pass | task planning (synonym) |
| P4 | pass (unrelated diagnoses included) | pass, headings English | pass | pass | language generation |
| P5 | **fail**: GLP-1 agonist and osteoporosis drugs missing | **fail**: same | pass | pass | task planning (drug classes) |

- **Before:** 4/10 fully correct (all English except P5). 0/5 German answers had German headings.
- **After:** 10/10 correct, and 5/5 German answers show German headings and a German "not documented" message.
- **Same facts in both languages (after):** share of identical fact statements per pair: P1 0.92, P2 0.71, P3 0.67,
  P4 0.95, P5 0.83. Every essential fact (drug, dose, schedule, value, date) appears in both languages with the same
  citation. The differences are lower-ranked "other relevant passages".
- **Source links:** all checked links passed the automatic integrity check, before and after.
- **Missing vs documented (P2):** kidney function is reported as "Not documented / Nicht dokumentiert" in both
  languages, separate from the documented contrast allergy and metformin.
- **Regression check:** the five official IBM screens are fact-for-fact identical to the deployed version (0 facts
  lost or added).
- **Latency:** 0.6–1.1 s per task locally. Hosted before the fix: 1.4–2.4 s.

### Optional claim verification (12 checks)

| Statement pair (EN / DE) | Before (EN / DE) | After (EN / DE) | Assessment |
|---|---|---|---|
| Takes Thrombo ASS 100 mg in the morning | supported / supported | supported / supported | correct |
| Latest HbA1c 7.9 % (record: 6.4 %) | contradicted / contradicted | contradicted / contradicted | correct |
| Penicillin allergy (not in record) | not documented / not documented | not documented / not documented | correct |
| Metformin 1000 mg three times daily / 1-1-1 | not documented / **contradicted (false)** | not documented / not documented | false contradiction removed; still a cautious miss |
| LVEF 35 % (record: 60 %) | not documented / not documented | contradicted / contradicted | fixed |
| Allergic to iodinated contrast media | not documented / not documented | not documented / supported | DE fixed; EN still a cautious miss |

- **Before:** 6/12 correct, with 1 false contradiction.
- **After:** 9/12 correct, 0 false contradictions, 0 false supports.
- `Patientin nimmt Metformin.` changed from not documented to supported.

**Phase 3 claim-verification set** (claims labelled by the authors; deterministic checks + NLI):

| Set | accuracy | false-support rate | contradiction recall | support recall |
|---|---|---|---|---|
| held-out, 34 claims (before → after) | 0.68 → 0.74 | 0.00 → **0.00** | 0.55 → **0.82** | 0.57 → 0.50 |
| development, 44 claims (before → after) | 0.66 → 0.75 | 0.04 → 0.04 | 0.57 → 0.71 | 0.65 → 0.70 |

The one development-set false support ("Es wurde eine Koloskopie durchgeführt.") existed before this change and is
still open.

## Fixes (this branch; not deployed)

1. **Task planning (`vocabulary.py`):**
   - New triggers: KM → allergy and contrast safety; metformin, GLP-1 and DM2/DM-II → glucose-lowering drugs;
     amaurosis, TIA, transient, monocular and episode → previous episodes; "Überblick" → diagnoses.
   - New `bone_health` concept (ATC M05 and A11CC).
   - The plan trigger "therap" now matches only at the start of a word, so "Osteoporosetherapie" no longer pulls in
     the cancer plan.
2. **Language (`planner.py`, `frontend_v1.py`):**
   - `request_language()` detects German from umlauts or ß, or from at least two German function words or clinical
     word stems.
   - German requests get German section headings (`TITLE_DE`), German fixed block titles and a German "not
     documented" message.
   - Source quotes stay verbatim German in both languages.
3. **Verification (`claim_verification.py`):**
   - The same equivalences are applied to claim and evidence: KM ↔ Kontrastmittel ↔ contrast media, LVEF ↔ EF ↔
     ejection fraction, allergic ↔ Allergie.
   - Brand and ingredient names map to the same ATC code using the existing drug lexicon (Glucophage ↔ metformin).
   - Units such as mg no longer count as shared topic words, and neither does "bekannt"/"known".
   - Lexicon drug names are added to the evidence search.
   - The NLI model sees evidence with brand names glossed ("Glucophage (metformin)") and KM spelled out. Citations are
     unchanged.

## Remaining limitations

- **Partly English in German answers:** structured fact statements (drug rows such as "1-0-0
  (morning-noon-evening)", diagnosis names such as "Malignant neoplasm of breast") and the frontend's own labels stay
  English.
  - What is German: headings, fixed block titles, the "not documented" message, and all source passages.
  - Full translation would need localized fact renderers. That is a larger change and was not made.
- **Extra content:** some unrelated content is still included (e.g. oncology plans in the English TIA answer,
  triggered by "therapy"). Weak "other relevant passages" can appear in the summary.
- **Verification:** English schedule wording ("three times daily") and the English contrast-allergy phrasing are not
  yet matched to the German record. They stay "not documented" (cautious, never a false support).
- **Scope:** one synthetic patient and 5 task pairs. The task pairs were written by us after the first run exposed
  gaps, so the after-fix result is not a held-out validation.
- **Browser check:** the German headings were not checked in the browser on the published Lovable app, because
  production was not redeployed.
