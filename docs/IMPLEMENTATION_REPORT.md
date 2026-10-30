# Implementation report (Milestones A–E)

Research prototype on synthetic data. Not a medical device; no clinical validation has been performed.

## Flow
`POST /api/tasks {patient_id, request}` → Layer 4 plan (LLM via OpenAI-compatible API, validated by Pydantic; heuristic
fallback if unavailable/invalid) → Layer 5 structured-first retrieval over Layer 3 facts (+ lexical search, RRF) →
Layer 6 claim verification + conflict detection → typed response (sections, claims, citations, missing, conflicts,
timeline, provenance, timings). The React UI (Layer 7) renders only this response; citations open the original passage.

## Status
| Component | Status |
|---|---|
| L1 ingestion/provenance, medSpaCy sectionizer | implemented, tested |
| L2 rules extraction, German ConText, ATC/ICD-10/LOINC subsets | implemented, tested |
| L2 GERNERMED++ (isolated env) | optional; corroboration only |
| L2 LLM extraction | implemented; tested with fake provider only |
| L3 PostgreSQL/SQLite, Alembic, incremental ingest, as-of queries, German FTS | implemented, tested |
| L4 planner: LLM (tested with Groq `openai/gpt-oss-120b`) + heuristic fallback | implemented, tested |
| L5 structured-first retrieval, lexical RRF | implemented; **no semantic/vector retrieval** |
| L6 claim verification, deterministic conflicts, review audit | implemented, heuristic |
| L7 React + TS UI | implemented; types generated from OpenAPI |
| Docker Compose (Postgres, API, nginx UI) | images build; full-stack compose run not yet executed |
| SNOMED CT, Austrian MEL, FHIR/ELGA export | not implemented |

## Benchmark (IBM `cases/`, patient-0000-0001, 15 questions)
Run: `python -m backend.app.tools.run_benchmark --cases <ibm>/cases`. The system receives only the situation text;
`expected.json` is read afterwards for scoring. Scoring is automatic key-term + source-document matching (an
approximation — review `artifacts/benchmark/situation_*.json` manually).

| Planner | Auto-pass | Slowest situation | Claims with all citations verified |
|---|---|---|---|
| heuristic fallback | 15/15 | 0.47 s | 347/347 |
| LLM (Groq gpt-oss-120b) | 15/15 | 4.5 s | 248/248 |

Detected source conflicts (8): two BMI/height/weight mismatches, lymphadenopathy present vs absent, left/right carotid
stenosis, inconsistent admission date, invalid discharge date `15.04.20156`, two admission blood-pressure values,
reused case number 20150610.

Key terms not matched in the automatic check: "ductal" (2.1), "5 µg" (3.1), "eye" (4.1), the literal phrase "not
documented" (4.2), and with the LLM planner also "amaurosis" (4.1). The lexicons and planner vocabulary were partly
tuned while inspecting these 15 questions, so this is **not** an unbiased held-out score.

## Run
```
docker compose up --build   # IBM_DATA_DIR=<ibm>/data/patient-0000-0001 to ingest; UI http://localhost:8080
# or dev: uvicorn backend.app.api.main:app --port 8000 ; cd frontend && npm run dev
LLM: LLM_PROVIDER=openai OPENAI_BASE_URL=https://api.groq.com/openai/v1 OPENAI_MODEL=openai/gpt-oss-120b OPENAI_API_KEY=...
```
