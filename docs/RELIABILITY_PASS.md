# P0/P1 reliability pass: results

Synthetic IBM patient-0000-0001 (8 German documents), PostgreSQL 16. IBM data mounted read-only, never committed.

## Citation integrity vs. claim support (Layer 6)
- `verify_citation` checks exact source version (`source_id`), patient, current version, `document_id`, stored and
  declared SHA-256, passage membership (source + patient), offsets inside the passage, quote = projected original slice,
  `passage_text` = stored passage, document date <= `as_of`. Failures are listed in `Citation.integrity_errors`.
- Semantic support is a separate stage (`Claim.support_basis`, `Claim.support_checks`): fact ownership/currency,
  assertion polarity, claim numbers present in the cited source, derived values only from verified inputs, conflicts,
  model-only extractions -> `verification_incomplete`. A valid citation alone never yields `supported`.
- Adversarial tests: `tests/test_citation_integrity.py` (forged passage, other patient's passage, shifted offsets,
  modified quote/passage text, mismatched document id, unknown/superseded version, checksum tampering, altered value).

## Model components actually executed (ingest, `ingest_store --llm --section-engine medspacy`)
| component | version | status |
|---|---|---|
| medSpaCy Sectionizer | medspacy 1.3.1; spacy 3.7.5 | ran |
| German rules | rules-de 0.1.0 | ran |
| German ConText (native) | de-context-0.1 | ran |
| GERNERMED++ (isolated env) | GERNERMEDpp_GottBERT 1.0.0 (spaCy 3.2.3) | ran (VM); disabled in Docker |
| LLM structured extraction | Groq openai/gpt-oss-120b | ran: 46-53 accepted, 0-1 rejected per run; earlier run hit 429 -> now reported `partial`/`failed` |

Docker image installs `.[postgres,api,clinical]` (medSpaCy ran in the container). GERNERMED++ is not baked in
(spaCy 3.2 pin, unspecified licence) and is reported as `disabled`.

## Benchmark (`run_benchmark`, automatic string checks, not clinical accuracy)
| | heuristic planner | Groq planner + LLM extraction |
|---|---|---|
| IBM 15: key terms | 57/61 | 52/61 approx (7 questions with omission candidates) |
| IBM 15: exact values in supported claims | 27/28 | lower (3.3 weights missed by LLM plan, 5.3 stenosis) |
| IBM 15: citations integrity-valid | 15/15 questions | 15/15 |
| IBM 15: unsupported (needs review) claims | 0 | 20 per question in situation 2 (LLM facts are review-only) |
| 10 author-written new tasks: exact values | 23/23 | 22/23 |
| median / slowest task | ~0.5 s / 0.9 s | 12.7 s / 22.4 s |

Caveats: lexicons were tuned while inspecting the 15 IBM questions; the 10 new tasks were written by the same author
(private file outside the repo) and exposed 3 retrieval gaps (TAPSE, Holter heart-rate range, "penicillin allergy /
smoking not documented") that were then fixed, so they are no longer held-out either.

Commands:
```
DATABASE_URL=... python -m backend.app.tools.run_benchmark --cases <ibm>/cases --new-tasks <private>/new_tasks.json --out artifacts/bench_heuristic
LLM_PROVIDER=openai OPENAI_BASE_URL=https://api.groq.com/openai/v1 OPENAI_MODEL=openai/gpt-oss-120b OPENAI_API_KEY=... \
  DATABASE_URL=... python -m backend.app.tools.run_benchmark --cases <ibm>/cases --new-tasks ... --llm --out artifacts/bench_groq
```

## Docker Compose smoke test
- First run failed: backend exited with `Missing patient identity in /data/documents/12340008.json` (patient id comes
  from the `patient-*` directory name, lost when mounted as `/data`). Fixed with `backend/docker-entrypoint.sh`
  (mount the parent of `patient-*` dirs; each patient is ingested).
- After fix: API healthy 11 s after `up` (ingest 284 facts incl. medSpaCy), frontend 200, ports bound to 127.0.0.1.
- Unexpected German request (speech therapist, swallowing assessment): Groq plan, 2.7 s API / 3.4 s UI, 5 claims all
  supported, 15/15 citations valid. English request (physiotherapist, mobilisation): 3.7 s API / 3.9 s UI, 20 claims
  supported, 44/44 citations valid. Clicking citations in the UI opened document 12340012 with the cited passage
  highlighted; no browser console errors.

## Security boundary
See `docs/SECURITY_AND_AUTH.md`: demo-only guard, loopback ports, optional shared demo token, no user auth.

## Generalisation tests
`tests/test_generalization.py`: 5 unseen roles x 2 patients, unknown drug (kept uncoded), month/ISO `as_of`, medication
change across admissions, missing data, present-then-negated diagnosis conflict, patient isolation, named allergen and
smoking reported missing.
