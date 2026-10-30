# Implementation plan — evidence-first, externally extensible

## Product acceptance / hackathon

- 5 situations / 15 benchmark questions, evaluated against the provided `expected.json` **only in tests**.
- 100% displayed facts have correct sentence/row links.
- No unsupported facts on the screen.
- >=5 genuine conflicts, no false alarms caused by temporal change or IBM extraction differences.
- End-to-end response latency <10 s across 5 situations (measure cold/warm separately).
- Novel English clinician tasks concerning the same synthetic patient; additional synthetic patients as a generalization check.
- Never publish the IBM `data/` folder.

## Roadmap and gates

| Stage | Deliverable | Done when |
|---|---|---|
| 0 | Source audit, project conventions, tests | IDs and document references pass; no source text in packaged ZIP |
| 1 | Layer 1 ingestion and provenance | 100% reversible offsets; heading/row/paragraph tests, raw text immutable; BioC optional interchange |
| 2 | Layer 2 information extraction | Medication/observations/diagnoses; status & time; source citations; benchmarked against independently annotated sample |
| 3 | Layer 3 clinical store | Persist source/evidence/facts and versions; patient isolation; as-of queries; optional FHIR export |
| 4 | Layer 4 planner | Open-ended instructions to typed, read-only operations; authorization separately enforced |
| 5 | Layer 5 retrieval and reasoning | Structured-first exhaustive lookup + lexical/semantic when needed; deterministic temporal comparisons |
| 6 | Layer 6 assurance | Claim-level source checks, contradictions and missing facts; explicit review flags |
| 7 | Layer 7 UI | Patient/tasks/results, visible citations, document highlighting, unknowns/conflicts, review workflow |
| 8 | Evaluation, integration & packaging | End-to-end tests, synthetic adversarial tasks, run instructions, UI demonstration, metrics |

## Research components: real usage, not name dropping

- Layer 1: medSpaCy custom German section rules; source location and stand-off annotation model inspired by BioC; ELGA CDA / FHIR adapters are independent modules. medSpaCy ships **no German section rules** by default.
- Layer 2: evaluate GERNERMED++ for German medication NER; deterministic medication row parser; German negation/context; concept mapping via local permitted terminology; LLM for complex extraction with typed outputs and explicit evidence.
- Layer 3: temporal events, immutable source versions, evidence references; PostgreSQL, SQLAlchemy, optional FHIR R4 transform.
- Layer 4: clinician task interpretation via schema-constrained LLM, read-only tool plans, independently applied authorization.
- Layer 5: structured SQL, exact/lexical search and optional BGE-M3/reranking; do not use top-k for "all medications" or exhaustive questions.
- Layer 6: deterministic provenance and temporal rules plus evidence-based verifier; never equate source-supported with medically true.
- Layer 7: React / TypeScript; display original passages and review states.

## Engineering guardrails

- One canonical interface per layer; no hidden hard-coded IBM benchmark answers.
- Provenance includes exact original character offsets + content hash.
- Dates: separate document, event, assertion and ingestion times; preserve dates with unknown day.
- No accidental normalization of German original text before citation location calculation.
- Original structured extraction from IBM is a candidate index, not medical ground truth.
- No patient data in Git, telemetry, logs or external LLM API without proper permission.
- Expensive ML inference can run at ingest-time; query-time should be index-first.
- Any unvalidated model integrations are identified explicitly in README and tests.

## Papers / standards

- medSpaCy: https://pmc.ncbi.nlm.nih.gov/articles/PMC8861690/
- BioC: https://academic.oup.com/database/article/doi/10.1093/database/bat064/341301
- GERNERMED++: https://pubmed.ncbi.nlm.nih.gov/37838290/
- ArchEHR-QA: https://aclanthology.org/2025.bionlp-1.34/
- FHIR R4: https://hl7.org/fhir/R4/
- Austria ELGA: https://www.elga.gv.at/technischer-hintergrund/technische-elga-leitfaeden/
