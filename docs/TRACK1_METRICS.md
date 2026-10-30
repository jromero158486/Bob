# Track 1 metrics: definitions, method and results

The organisers' metrics come from the Track 1 README in the IBM challenge ZIP ("Metrics"). We report them **exactly as
defined there**, measured on the deployed system (backend `b814c70` on Exoscale + the published Lovable app). Results
of different kinds are kept in separate sections. We claim no clinical validation.

**Dataset:** the IBM synthetic patient `patient-0000-0001` (8 German documents, 2015–2016) and the 5 official
situations with 3 questions each (15 questions) from `cases/situations.md`. Expected answers come from
`cases/expected.json`, which is only read by the human grader and never by the system. The `data` folder is not in
this repository.

## A. Official IBM metrics (5 situations, 15 questions, production)

**Input:** each situation's title and description, copied verbatim, with the role noun (Anaesthetist, Surgeon,
General practitioner, Emergency physician, General practitioner). **Grading:** by hand against the original
documents, in the browser on the published app.

| Metric | Official definition (Track 1 README) | How we measured | Result | Target |
|---|---|---|---|---|
| Correct answers | Expected answer visible without clicking (scrolling allowed), linked to a source document; "not documented" needs no link | strict hand-grading in the browser: nothing expanded, every qualifier in `expected.json` must be on screen | **12 / 15 correct, 3 partial, 0 failed** | 15 / 15 |
| Traceability | Share of facts on screen whose link shows the right passage | automatic: each evidence quote must equal its section text at the stored offsets **and** appear in the original document; plus one citation per situation opened in the browser | **100%**: 463 facts, all linked, 755 links, 0 broken | 100% |
| Invented facts | Facts on the 5 screens that are not in the documents | hand review of the answer facts; a later blind evaluation found one we missed | **1**: "Atrial fibrillation — VHF" (from the question line of a Holter request; the Holter showed sinus rhythm), on 4 of 5 screens | 0 |
| Contradictions | Real contradictions shown minus false alarms; each counts once; all passages linked | hand review of the "Potential conflicts" block | **8 flagged: 7 real, 1 false alarm (140/90 vs 145/90 mmHg, a small measurement difference) → +6** | ≥ 5 |
| Load time | Slowest of the 5, from submitting to the complete screen | browser stopwatch on the published app | **2.16 s** (S4); all five 1.32–2.16 s | < 10 s |

**The three partials:**
- 1.3: "normal systolic function" appears only in the cited source, not on screen.
- 3.2: "no later HbA1c documented" is not stated.
- 3.3: the 67 kg weight shows the letter date (5 April 2016), not the visit date (4 April 2016).

A borderline item that is not counted above: the contrast allergy is shown as "iodinated", but the source only says
"KM-Allergie" (contrast medium).

**Baseline:** the first audit of the earlier deployment (`8acac85`) scored 12/15 under a more lenient reading, with
2 partial and 1 failed (4.1, 4.2, 5.1). All three are correct in `b814c70`. An earlier local API run scored
"15/15 clinically complete" under a lenient reading; the strict browser result above is the one we report.

**Limitations:** single patient; we saw these 15 questions while building the rules, so this is a regression
benchmark, not held-out validation; single grader.

## B. Blind adversarial evaluation (20 new questions)

These questions were written after the freeze, with expected answers recorded before running. Details:
[ADVERSARIAL_EVAL.md](ADVERSARIAL_EVAL.md).

| Correct | Partial | Incorrect | Appropriately abstained | Broken citations | Latency |
|---|---|---|---|---|---|
| 5 | 11 | 4 | 0 of 2 expected (plus 1 false refusal) | 0 / 2,384 | 1.0–2.6 s |

## C. Retrieval and verification experiments (internal, small samples)

From [SCIENTIFIC_REPORT.md](SCIENTIFIC_REPORT.md) and [RELIABILITY_RESULTS.md](RELIABILITY_RESULTS.md); same patient.

| Experiment | Data | Baseline | Result |
|---|---|---|---|
| Passage retrieval, fact recall@10 | 28 EN/DE queries, 44 hand-reviewed gold passages | lexical 0.09 | **BGE-M3 dense 0.57** (production); hybrid + reranker 0.63, but about 7 s per search on CPU, so not deployed |
| Claim verification (optional "Verify clinical statement") | 34 held-out claims | deterministic only: false-support 0.20, contradiction recall 0.00 | deterministic + NLI (production): **false-support 0.00**, contradiction recall 0.82, support recall 0.50 |
| English/German task pairs | 5 pairs (10 tasks), author-written | deployed before the fix: 4/10 | 10/10 with the same facts and citations ([MULTILINGUAL_RESULTS.md](MULTILINGUAL_RESULTS.md)) |
| Edge cases | 12 author-written cases | – | 11 pass, 1 partial in production ([RELIABILITY_RESULTS.md](RELIABILITY_RESULTS.md)) |

The multilingual and edge-case tasks shaped later rules, so they are regression tests.

## D. Production browser audit

Published Lovable app + `b814c70`:
- 48 clinical API calls, all HTTP 200, all `origin: live`, no fixture data.
- Source highlights match the exact German span.
- Medication comparison, timeline and review persistence all work.
- Ordinary tasks never call the NLI.
- All 4 services healthy, with no restarts.

Details: production section of [RELIABILITY_RESULTS.md](RELIABILITY_RESULTS.md).

## Reproduce

```bash
python -m venv .venv && .venv/bin/pip install -e ".[api,postgres]"
export CLINICAL_API_TOKEN=<demo token>       # hosted only; not needed for a local backend without DEMO_API_TOKEN
.venv/bin/python -m evaluation.judging.hosted_ibm_audit \
  --base https://85-217-172-189.sslip.io/api/v1 \
  --cases <ibm-zip>/cases --data <ibm-zip>/data --out artifacts/judging/run \
  [--extra tasks.json]                       # optional new questions: [{"role": "...", "task": "..."}]
```

The script sends only the situation text. It writes the raw screens (`S1.json`, `S1.txt`), latency and the automatic
citation check (`summary.json`) to the git-ignored `artifacts/`. Correctness, invented facts and contradictions are
graded by hand against `expected.json` and the documents. For a local backend, use
`--base http://localhost:8000/api/v1`. Browser steps: [DEMO_SCRIPT_IBM.md](DEMO_SCRIPT_IBM.md).
