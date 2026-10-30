# Judge-readiness audit — IBM Track 1

**Audit date:** 30 Oct 2026 · **Benchmark:** original IBM Track 1 ZIP (`cases/situations.md`, `cases/expected.json`) · **Patient:** `patient-0000-0001` (8 synthetic German documents)

**System under test**
- Published frontend: https://screenshot-stitchery-studio.lovable.app (screenshot-match `main` @ `1a2b9bc`)
- Hosted backend: Exoscale `at-vie-1`, Bob commit **`8acac85`** (branch `devin/1793355676-labs-and-short-drug-verify`, PR #1)
- Planner `heuristic` (no LLM in the main flow), retrieval BGE-M3 dense over pgvector, reranker off, optional NLI `mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`

> The repository is public, so this report does not reproduce the IBM expected answers or patient source text. Per-question values were graded against `cases/expected.json` and the original documents. The raw API payloads are written to the git-ignored `artifacts/judging/`. Re-run with [the demo script](DEMO_SCRIPT_IBM.md).

## How it was measured

1. **API run** (`evaluation/judging/hosted_ibm_audit.py`): each official situation is sent to the hosted `/api/v1/clinical-tasks` as `role` + `"{title}. {description}"`, exactly as in `situations.md`. Nothing from `expected.json` is sent or used by the system. Every evidence link is checked automatically: the backend offsets must reproduce the quote inside its section, and the quote must occur in the original IBM document.
2. **Manual clinical grading:** every expected value, date, dose and schedule was compared with the returned facts and their cited document IDs. Keyword overlap alone never counted as correct.
3. **Browser audit on the published Lovable URL:** a recorded run of all five situations with the exact texts. It checked whether each answer is visible **without expanding any accordion** (scrolling allowed), opened one citation per situation to confirm the exact German highlight, and measured UI latency.

## Results — five IBM metrics

| Metric (IBM definition) | Target | Result |
|---|---|---|
| **Correct answers:** visible without clicking, with source link | 15/15 | **12/15 fully correct**, 2 partial, 1 failed (details below) |
| **Traceability:** displayed facts linked to the right passage | 100% | **456/456 facts (100%)** carry source links. **747/747 links (100%)** pass the automatic offset and original-document check. Manual: all 15 answers cite the correct document, and 5/5 opened citations highlighted the exact German span. |
| **Invented / unsupported facts** on the five screens | 0 | **0 found** in the manual review of the answer facts. Facts with internal disagreement are labelled *conflicting*, not *supported*. Not every one of the 456 displayed facts was reviewed by hand. |
| **Contradictions:** real minus false alarms | ≥ 5 | **8 flagged: 7 real (1 borderline), 1 false alarm → net +6.** Normal changes over time are shown as changes, not conflicts (see below). |
| **Load time:** slowest of five | < 10 s | **UI: 1.25–1.86 s, slowest 1.86 s (S4); all five total 7.3 s.** API-only re-runs: 1.69–2.09 s. |

### All 15 questions

"Visible" = rendered in the published UI without expanding an accordion.

| # | Situation / question topic | Values, dates, doses | Source docs | Visible | Result |
|---|---|---|---|---|---|
| 1.1 | Anaesthetist: antithrombotic medication | exact drug, dose, schedule | correct | yes | **Correct** |
| 1.2 | Anaesthetist: allergies + reactions | allergen and all 3 reactions (in German) | correct | yes | **Correct** |
| 1.3 | Anaesthetist: cardiac function | exact value + date | correct | yes | **Correct** |
| 2.1 | Surgeon: histology, side, TNM | exact | correct | yes | **Correct** |
| 2.2 | Surgeon: receptors, HER2, Ki-67 | all percentages + Allred scores | correct | yes | **Correct** |
| 2.3 | Surgeon: planned procedure + date | exact | correct | yes | **Correct** |
| 3.1 | GP diabetes: glucose-lowering drugs | all 3 drugs, doses, schedules, route | correct | yes | **Correct** |
| 3.2 | GP diabetes: latest HbA1c | exact value + date. "No later value" is implicit, not stated. | correct | yes | **Correct** |
| 3.3 | GP diabetes: weight course | all 3 weights + calculated change | correct | yes | **Correct** |
| 4.1 | ED: similar previous event + cause | event, symptoms, side and stenosis are each shown, but the **causal link is not stated** | correct | parts | **Partial** |
| 4.2 | ED: contrast-imaging risks | allergy and metformin shown; **"kidney function not documented" missing** | correct | parts | **Failed** |
| 4.3 | ED: antihypertensive medication | exact drug, dose, schedule | correct | yes | **Correct** |
| 5.1 | GP follow-ups: what was recommended | all 3 follow-ups shown; **imaging interval only visible after opening the source** | correct | parts | **Partial** |
| 5.2 | GP follow-ups: was imaging done? | "no later document records that it took place" | correct | yes | **Correct** |
| 5.3 | GP follow-ups: side/degree of stenosis | exact; the left/right inconsistency is flagged | correct | yes | **Correct** |

A keyword-coverage score would rate 4.1, 4.2 and 5.1 higher. We do not count them as correct, because the clinically required statement is not on the screen.

### Contradictions

| Flagged conflict | Verdict |
|---|---|
| BMI inconsistent with height/weight (2015 letter) | real |
| BMI inconsistent with height/weight (2016 outpatient letter) | real |
| Two admission dates in the 2016 discharge letter | real |
| Invalid discharge date in the 2016 discharge letter | real (typo) |
| 2015 case number reused for the 2016 stay | real |
| Same carotid finding described on left and right across reports | real; the label is imprecise about which finding |
| Palpable axillary nodes vs. no enlarged nodes on later ultrasound | real but borderline (palpation vs. imaging) |
| Admission blood pressure 140/90 vs 145/90 in one letter | **false alarm** (small measurement difference) |

Correctly treated as **changes over time, not conflicts:** the candesartan schedule change between 2015 and 2016 (shown in the medication comparison) and the 78 → 67 → 66 kg weight course (shown as a calculated change).

## Generalization — new English tasks (not in the benchmark)

Hosted API, run against `8acac85`, with the same automatic link checks (0 bad links in all tasks).

| # | Role / request | Latency | Result |
|---|---|---:|---|
| N1 | Cardiologist: "Referral review: summarize her cardiovascular risk factors and the results of the most recent cardiac investigations." | 2.1 s | **Pass.** Risk factors, LVEF/TAPSE, ECG, echo, 24 h BP, carotid stenosis, ASS, candesartan. Noise: oncology procedures in a procedures block. |
| N2 | Clinical pharmacist: "Medication reconciliation: list all current medications with doses and flag any dose changes since 2015." | 1.7 s | **Pass.** Full current list with doses and the candesartan schedule change with both dates. |
| N3 | Oncologist: "Summarize current cancer treatment plan and relevant labs." *(known limitation 1)* | 2.2 s | **Pass after the PR #1 fix.** The labs block now shows the latest HbA1c. Absent creatinine/eGFR is not listed as "not documented". |
| N4 | Radiologist: "She needs a CT angiography with iodinated contrast. Check allergies, kidney function and metformin." | 1.4 s | **Pass with one error.** Shows the allergy, metformin and "Kidney function: not documented". **It also wrongly lists "Check allergy: not documented"**, even though the allergy is shown above it. |
| N5 | Ophthalmologist: "Follow-up of the transient vision loss in her left eye in 2015: what was found and which eye examinations were recommended?" | 2.2 s | **Partial.** Finds the 2015 symptoms, the stenosis and the eye check-ups (and that no later record shows them done), but the summary leads with unrelated 2016 oncology plans. |
| N6 | Ward nurse: "Admission check: allergies, smoking status, body weight and anticoagulants (ASS)." *(known limitation 2, task side)* | 1.8 s | **Pass.** ASS dose/schedule, allergy, weight history, "Smoking status: not documented", date conflicts. |

Optional claim verification with medication abbreviations (*known limitation 2, verification side*):

| Statement | Verdict | Assessment |
|---|---|---|
| `Patient nimmt ASS.` | supported; the Thrombo ASS passage is shown first | correct (fixed in PR #1) |
| `Patient nimmt ASS. HbA1c 7,9 %. Penicillinallergie.` | supported / contradicted / not addressed | correct |
| `Patient takes ASS 100 mg once daily.` | not addressed | conservative miss (English schedule wording) |
| `The patient takes aspirin.` | not addressed | conservative miss (no generic-name or English mapping in verification) |
| `Patientin nimmt Marcumar.` | not addressed | correct (not documented) |

## Clinician experience (published Lovable URL)

| Check | Result |
|---|---|
| Different role/task → different relevant screens | **Pass** |
| All critical answers visible without opening accordions | **Fail** for 4.2 (kidney warning absent) and 5.1 (interval only in source); all other answers pass |
| Citations open the original German document with an exact highlight | **Pass** (5/5 spot checks, one per situation) |
| Missing information distinct from documented negatives | **Pass** ("Not documented" smoking status vs. blue "Documented negative" pericardial effusion) |
| Conflicting evidence side by side | **Fail.** Conflicts show an explanation and source buttons, not the competing passages next to each other. |
| Medication comparison and longitudinal history | **Pass** (candesartan 2015 vs 2016; dated timeline) |
| Human review | **Pass.** One escalation was stored (HTTP 200). |
| Optional NLI verification | **Pass.** Three correct verdicts, decisive evidence first, about 2 s. Normal tasks made 0 verification calls. |
| No fixture results | **Pass.** All 28 captured API calls went to the hosted `/api/v1` and returned 200; every response was `origin: "live"`; "Live backend" badge shown. |

## Known limitations (not fixed, to protect the deployed demo)

English/German generalization (10 new tasks, 12 verification checks) and the fixes for it, which are on a branch and not deployed: [MULTILINGUAL_RESULTS.md](MULTILINGUAL_RESULTS.md). The fixes for gaps 4.1, 4.2 and 5.1 (15/15 on the API screens), the edge cases and the Gemini assessment are also on a branch and not deployed: [RELIABILITY_RESULTS.md](RELIABILITY_RESULTS.md).


1. A situation that mentions contrast imaging only implicitly (4.2) does not trigger the kidney-function missing-information check. An explicit request (N4) does.
2. Causal statements from the letters (4.1) appear as source passages, not as a linked explanation.
3. Follow-up statements omit the recommended interval (5.1). The interval is in the cited passage and in the planned-procedures block.
4. The conflict view lists explanations with source buttons rather than side-by-side passages.
5. Over-inclusion: long procedure lists and older plans appear on unrelated tasks (S2, N1, N5).
6. One false "not documented" item when a request says "check allergy" (N4).
7. Claim verification maps German abbreviations but not English generic names or English schedule wording.
8. One synthetic patient only; the 15 questions informed the rule vocabulary, so they are not a held-out test. The new English tasks are a small generalization probe, not a validation.

## Deployment health at audit time

- Exoscale VM `lumen-demo` (4 vCPU / 8 GB): `backend`, `models` (healthy), `db` (healthy) and `caddy` were up with 0 restarts and no OOM. About 4.9 GB RAM available, disk 42% used.
- `GET /api/health` → 200 (0.5 s). `/api/v1/*` without the token → 401. Published Lovable site → 200 and live-backend badge.
- Rollback: `main` (pre-PR #1) and the Exoscale disk snapshot.
