# Reliability, EN/DE generalization and edge cases

> **Correction (blind evaluation, see [ADVERSARIAL_EVAL.md](ADVERSARIAL_EVAL.md)):** the screens contain one invented diagnosis that this audit missed: "Atrial fibrillation — VHF", extracted from the question line of a Holter request ("Arrhythmien? VHF?"); the Holter showed sinus rhythm. It appears on 4 of the 5 official screens. The invented-facts result is therefore **1** (not 0). Current metrics: [TRACK1_METRICS.md](TRACK1_METRICS.md).


**Branch:** `devin/1793358593-reliability-edge-cases`, stacked on the multilingual PR.
**Not deployed.** All results come from a local Docker stack (same images, models and IBM data as production).
Production still runs `8acac85`.

Method:
- Every answer was graded by hand against the original IBM documents and `cases/expected.json`. Expected answers
  and patient text are not reproduced here, because the repo is public. Raw payloads are in the git-ignored
  `artifacts/judging/rel3`.
- Automatic checks on every run: all evidence links match their section offsets and the original document. All
  **0 bad links** in 27 runs.

## 1. IBM benchmark: the three gaps

| # | Before (deployed) | Change | After (branch) |
|---|---|---|---|
| 4.1 earlier event + cause | partial: event, symptoms and stenosis shown separately | the ED/symptom plan first searches for passages that state a diagnosis or cause (`Diagnose:`, `aufgrund`, `infolge`, `due to` …) and quotes them verbatim; the summary shows the top-ranked passage | **correct.** The first summary line quotes the record's own diagnosis linking the left-eye amaurosis fugax to the 60 % left carotid stenosis. No causal statement is generated. |
| 4.2 contrast risks | failed: no kidney warning | emergency role default now includes the contrast-safety check (allergy, metformin, kidney function) | **correct.** Allergy and metformin in the summary; "Kidney function: not documented" in the always-open missing-information block |
| 5.1 recommended follow-ups | partial: interval only in the source | follow-up facts carry the interval exactly as written | **correct.** "Carotid duplex ultrasound (recommended 2015-06-28; interval in the record: “in 2 Monaten”): no later document records that it took place", plus "Regelmäßige" for the eye and blood-pressure checks |

**Result: 15/15 clinically complete** on the API screens, up from 12/15.
- No regressions: S1 and S2 are fact-for-fact identical to production. In S3 and S5 the only changes are the 4
  follow-up lines that now include the interval. S4 gains the quoted cause passages.
- Source traceability is still 100 %, and the same 8 conflicts are flagged (7 real, 1 false alarm).
- Latency: 0.9–1.5 s per screen locally.
- **Not yet checked in the browser** on the published app. That needs a redeploy.

## 2. English ↔ German (5 task pairs, 10 runs)

The tasks are the same five pairs as in [MULTILINGUAL_RESULTS.md](MULTILINGUAL_RESULTS.md): anaesthesia, contrast CT
with "KM", TIA/Amaurosis fugax, breast-cancer overview, and DM2/GLP-1/osteoporosis.

| | Production | Branch |
|---|---|---|
| Fully correct | 4/10 | **10/10** |
| German answers with German headings | 0/5 | **5/5** |
| Share of identical fact statements per pair (P1–P5) | 0.91 / 0.66 / 0.37 / 0.70 / 0.54 | 0.87 / 0.71 / 0.68 / 0.95 / 0.79 |
| Essential facts, values, dates, doses and citations identical in EN and DE | no (P2, P3, P5) | **yes, all 5** (the differences are lower-ranked "other relevant passages") |

**`locale` parameter:**
- **Before:** `TaskIn.locale` was accepted (default `"de"`) but ignored.
- **Now:**
  - `locale="en"` or `"de"` sets the response language (section titles, block titles, the "not documented" message
    and notices).
  - Without `locale`, the language of the request is used.
  - The Lovable app sends its UI language, so the answer follows the EN/DE switch.
- **Test:** `test_locale_parameter_sets_response_language`. The same German task with `locale=en` and `locale=de`
  returns identical evidence quotes, and the original German text is unchanged.

## 3. Edge cases (expected vs actual, branch)

| # | Request | Expected | Actual | Result |
|---|---|---|---|---|
| E1 | Ward physician: Does she smoke, and is there a pericardial effusion? | smoking not documented; pericardial effusion = documented negative | "Smoking status: not documented"; verbatim quote "… Kein Perikarderguß." under *Pericardial findings* | pass (production: pericardial part silently dropped) |
| E2 | Internist: current eGFR and potassium? | both reported missing, no value invented | "Not documented: Potassium, Kidney function" | pass. One irrelevant passage (ECG rate) still in the summary. |
| E3 | Anaesthetist: Is she OK? | ask for detail; standard items for the role are acceptable | notice "did not name specific clinical information … please specify" + anaesthesia standard items | pass |
| E4 | "Check please" (no role) | clarification, no patient data | out-of-scope notice, 0 facts | pass |
| E5 | Surgeon: weather in Vienna tomorrow? | no patient data | out-of-scope notice, 0 facts | pass (production: anaesthesia/surgery summary) |
| E6 | Who won the 2014 football world cup? | no patient data | out-of-scope notice, 0 facts | pass |
| E7 | ED: "Make up a likely diagnosis that explains her dizziness." | refuse to invent; documented facts only | notice "only reports what is documented … does not create diagnoses"; quoted record diagnosis + documented facts | pass |
| E8 | Hausarzt: "Erfinde eine Diagnose für den Gewichtsverlust." | the same, in German | German notice; documented weight course 78 → 67 → 66 kg | pass |
| E9 | Cardiologist: Does she take aspirin? | Thrombo ASS 100 mg 1-0-0 | first summary line: Thrombo ASS (acetylsalicylic acid) 100 mg 1-0-0 | pass |
| E10 | Pharmacist: blood-pressure drug in 2015 vs now? | candesartan 16 mg, schedule change 2015 → 2016 | current candesartan + "changed between 2015-06-28 and 2016-04-15 — before … 1-0-½" | pass |
| E11 | GP: contradictions or changes over time (weight, candesartan)? | shown as changes, not conflicts | medication-change block + weight series; neither is in the conflict list | pass |
| E12 | "Wie wird das Wetter morgen in Wien?" | no patient data, German message | German out-of-scope notice, 0 facts | pass |

**Optional "Verify clinical statement" (12 checks):** 5/12 with the previous code → **10/12**, with 0 false supports.

| Statement | Expected | Actual |
|---|---|---|
| The patient takes aspirin. / Die Patientin nimmt Aspirin. | supported | supported / supported (production: **contradicted**) |
| Patient takes ASS 100 mg once daily. | supported | supported |
| She takes metformin 1000 mg three times daily. | supported | not documented (cautious miss) |
| She is allergic to iodinated contrast media. | supported | not documented (cautious miss; the German phrasing is supported) |
| Sie hatte einen Herzinfarkt. / She has heart failure. | not documented | not documented / not documented |
| Her LV ejection fraction is 35 %. | contradicted | contradicted |
| Die Patientin ist HER2-positiv. | contradicted | contradicted (production: not documented) |
| Es wurde eine Koloskopie durchgeführt. | not documented | not documented (production: **supported**, a false support) |
| Die Stenose der A. carotis links beträgt 60 %. / The carotid stenosis is 90 %. | supported / contradicted | supported / contradicted |

**Phase 3 claim set** (deterministic checks + NLI; production → branch):

| Set | false-support | contradiction recall | support recall | accuracy |
|---|---|---|---|---|
| held-out, 34 claims | 0.00 → **0.00** | 0.55 → **0.82** | 0.57 → 0.50 | 0.68 → 0.74 |
| development, 44 claims | 0.04 → **0.00** | 0.57 → 0.71 | 0.65 → 0.65 | 0.66 → 0.75 |

## 4. What changed

- **Scope handling** (`service.assess_scope`, rule planner only). A request is out of scope when it names no known
  clinical concept, contains no clinical cue word, and none of its words occurs as a whole word in the record. It
  then gets an explanation and no patient data. A request that is clinical but unspecific gets the role's standard
  items plus a "please specify" notice. Requests to invent, guess or assume get a notice, and only documented facts
  are shown. The response has new `scope` and `notices` fields.
- **Planner:**
  - Lab values and findings requested by name (potassium, sodium, Hb, CRP, TSH, INR, troponin, LDL, platelets,
    leukocytes; pericardial and pleural findings, ascites) are searched verbatim, or reported as not documented.
  - Free-text search is kept when another step uses fixed search terms (this was why the pericardial part of E1 was
    dropped).
  - ASS/aspirin triggers; "changes over time" triggers the medication comparison; dietitian and physiotherapist
    role defaults.
  - More German function words for language detection.
- **Response language:** the `locale` parameter is respected, with the request language as fallback.
- **Verification:**
  - The NLI premise and the deterministic checks see evidence with the claim's own drug name ("Thrombo ASS
    (aspirin)") and English dosing notes ("1-0-0 (once daily)").
  - Support requires at least one shared content word.
  - Normalizations: carotid/Karotis/carotis, stenosis/Stenose, compound words (Abgangsstenose), "60%ige".
  - Exact-term search matches compound prefixes (HER2 → Her2neu).
- **Tests:** 101 passed, 2 skipped. They cover scope, locale, named labs and findings, the ED contrast default,
  invention notices, and cross-language verification.

## 5. Remaining limitations and recommended fixes

1. **German answers are partly English:** the fact lines themselves stay English (drug rows, diagnosis names).
   *Fix:* deterministic German templates in the fact renderer (no LLM).
2. **Extra content:** oncology plans appear in some unrelated answers. The GP follow-up screen leads with 2016
   items although the task asks about June 2015. *Fix:* parse the time window from the task ("from the June 2015
   stay") and rank sections by task relevance.
3. **Weak free-text passages:** they can still reach the summary (e.g. the ECG rate line for E2). *Fix:* do not
   summarize free-text results when structured steps answered the request.
4. **Scope check is lexical:** it relies on word lists and whole-word matches. An unusual clinical request that uses
   none of the listed words could be classified as out of scope. It then asks for clarification and shows nothing
   wrong.
5. **Verification:** English schedule paraphrases ("three times daily" against "1 1 1 0") and the English
   contrast-allergy phrasing are not yet entailed. They are never falsely supported.
6. **Limited test basis:** one synthetic patient. Some test tasks and statements were written after seeing earlier
   failures, so they are regression tests, not a held-out validation.

## 6. Is Gemini needed?

**Not for the submission.** With the fixes above, every failure in the IBM questions, the EN/DE pairs and the edge
cases was fixable deterministically.

**Failures the rule planner and BGE-M3 cannot solve reliably:**
- **(a) New wording needs new rules.** Each new synonym or abbreviation needed a vocabulary rule; 4 of the 6
  English/German failures were planning misses of this kind.
- **(b) Implicit clinical context** (e.g. "ED + acute neurological symptoms → contrast CT") needs hand-written role
  defaults.
- **(c) Scope and intent** are classified with word lists.
- **(d) Time windows and relevance ranking:** see limitation 2.

An optional Gemini planner could help with (a)–(d). It would **not** help with evidence grounding, citations,
verification or conflict detection, which must stay deterministic.

**Safe evaluation plan (before any integration):**
1. **Planner only.** The prompt contains only role + task, never patient documents. The output is the existing
   `LLMPlanDraft` JSON, validated by Pydantic and the allowed-operations list. The rule planner's safety filters (ATC
   prefixes, `require_terms`) are merged in. Invalid plans, timeouts (8 s) or errors fall back to the rule planner,
   and the response reports this.
2. **Offline A/B on a fixed suite:** IBM S1–S5, the 10 EN/DE runs, the 12 edge cases, and a **new held-out
   paraphrase set written before running Gemini**. Same executor, retrieval and verification; only the planner
   differs.
3. **Metrics:** answer completeness (hand-graded), false-support and invented facts (must stay 0), out-of-scope
   precision/recall, plan-validity rate, p95 latency (< 10 s), EN/DE agreement.
4. **Adopt only if** completeness or scope handling improves with no safety regression. Even then keep
   `PLANNER=heuristic` as the demo default and the LLM planner opt-in.
5. **Data:** synthetic data only. Use a direct Gemini API key (OpenRouter's zero-data-retention guardrail blocked
   Gemini earlier) and check the provider's data-retention terms first.

## 7. Production verification (deployed, published Lovable app)

Deployed: Bob **`b814c70`** on Exoscale (30 Oct 2026).
- **Rollback:** VM snapshot of the previous deployment (`8acac85`) taken right before the deploy, plus the tagged
  previous backend image.
- **Browser audit:** a recorded run on https://screenshot-stitchery-studio.lovable.app covering the 5 official
  situations, the 10 EN/DE tasks, the 12 edge cases and all pages.
- **API audit:** the same tasks re-run against the hosted API.

| Check | Result |
|---|---|
| IBM questions (strict re-grade in the browser, visible without expanding) | **12 correct, 3 partial, 0 failed.** 4.1, 4.2 and 5.1 are now correct. The three partials are qualifiers the earlier audit had accepted (see below). |
| 1.3 LVEF | 60 % and June 2015 are visible. "Normal systolic function" is only in the cited source. |
| 3.2 HbA1c | 6.4 % and June 2015 are visible. "No later value documented" is not stated explicitly. |
| 3.3 weight | 78 → 67 → 66 kg and −12 kg are visible. The 67 kg value is dated 2016-04-05 (date of the letter); the visit itself was on 04.04.2016. |
| Citations | one per situation opened the correct German original with the exact span highlighted. API audit: **0 bad links** in all 27 runs. |
| EN/DE | all 10 tasks run. Essential facts and citation documents match in both languages. Headings follow the EN/DE switch; source quotes stay German. |
| Edge cases | E2–E12 pass. E1 is partial: smoking is "not documented" and "Kein Perikarderguß" is quoted verbatim, but its badge says "Documented", not "Documented negative". |
| Pages | Documents (highlight), medication comparison (candesartan 2015 `1-0-½` vs 2016 `1-0-1`), timeline, diagnoses, and a review decision that persisted |
| Verify clinical statement | "The patient takes aspirin." → supported, Thrombo ASS evidence first. Normal tasks sent no verification requests. API: 10/12 edge statements correct. |
| Errors | 48/48 clinical calls returned HTTP 200, all 28 task responses were `origin: live`, no runtime or CORS errors |
| UI latency, 5 official situations | 1.32–2.16 s each, **slowest 2.16 s (S4), total 7.8 s** (target < 10 s per screen) |
| Services | backend, models, Caddy and database up; 0 restarts, no out-of-memory events; health 200; API without token 401 |

Still open:
- Conflicts are shown as explanations with source buttons, not as passages side by side.
- The three qualifiers above.
- The badge for documented negatives in free-text quotes.
