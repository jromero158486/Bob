# Research implementation matrix

Status vocabulary (used everywhere in docs/research):
**implemented** = code exists in the pipeline · **enabled** = active in a documented configuration ·
**executed** = run on the IBM patient documents with logged component record · **evaluated** = metrics in
EXPERIMENTS.md · **partially reproduced** = the paper's algorithm runs but not its full setup/data ·
**blocked** = cannot be done here (reason given) · **inspiration only** = influenced design, not reproduced.

Baseline (commit 87c4089): 66 passed / 2 skipped (`.venv/bin/python -m pytest -q`); deterministic extraction
(`rules-de`) + native ConText + structured-first retrieval with lexical RRF are kept as ablation baselines.

| # | Method / technology | Official code · licence | Contribution | Integration (code path) | Status | Evaluation | Remaining work |
|---|---|---|---|---|---|---|---|
| 1 | medSpaCy (Eyre et al., AMIA 2021) | github.com/medspacy/medspacy · MIT | clinical sectionizer + ConText | `layer1_ingestion/processing/sections.py` (`engine=medspacy`, German rules) | implemented, enabled, executed (VM + Docker) | section agreement vs rules (51/51 headings) | German section rule set is small |
| 2 | ConText / NegEx (Harkema 2009; Chapman 2001) | via medSpaCy · MIT | negation, uncertainty, experiencer, temporality | `layer2_extraction/context.py` (native German), medSpaCy ConText optional | implemented, executed | Phase 1 negation set (EXPERIMENTS §1) | medSpaCy ConText drops German abbreviations |
| 3 | GERNERMED++ (Frei, Frei-Stuber, Kramer 2023) | github.com/frankkramer-lab/GERNERMED-pp · **no licence file** (preprint CC BY-NC-SA) | German medication NER (Drug, Strength, Route, Form, Dosage, Frequency, Duration) | `layer2_extraction/ner/gernermed.py` (isolated spaCy 3.2 subprocess; `associate_attributes`) | implemented, executed, **evaluated** (EXPERIMENTS §1b); disabled in Docker | drug 21/21, strength 17/17 agree, frequency 7/20, route 0/16 | licence unclear → not redistributed; pretrained model used as published, not retrained |
| 4 | BioC (Comeau et al. 2013) | github.com/bionlplab/bioc · MIT | interoperable annotation format | `layer1_ingestion/provenance/bioc_export.py` (`dumps_bioc(records, facts)`) | implemented, executed, tested (round-trip through `bioc.biocjson`) | every fact annotation's location slices the original text to its text | no relations exported yet |
| 5 | CARDIO:DE (Richter-Pechanski et al. 2023) | dataset via application (heiDATA, DUA) | German cardiology letters gold standard | evaluation only | **blocked** (restricted access, not obtained) | — | apply for access |
| 6 | LLM structured extraction (grounded JSON) | Groq `openai/gpt-oss-120b` via OpenAI-compatible API | relation/complex fact extraction with verbatim quotes | `layer2_extraction/llm/structured_extraction.py` + `ingest_store --llm` | implemented, enabled (opt-in), executed, **evaluated** (EXPERIMENTS §1b) | +40–45 facts, 0 rejected, all grounded; no change in silver-standard F1 | prompt not tuned; rate limits; all LLM facts needs_review |
| 7 | Terminology linking | local ICD-10/ATC/LOINC lexicons | candidate codes, never auto-verified | `layer2_extraction/terminology.py`; `structured_extraction.candidate_codings` for LLM spans | implemented (lexicon match only), executed | ICD-3 recall 0.661 vs IBM; misses are concepts absent from the lexicon | candidate retrieval + reranking over a full ICD-10-GM catalogue **not implemented** (catalogue not obtained); SNOMED CT **blocked** (licence) |
| 8 | BGE-M3 (Chen et al. 2024) | huggingface.co/BAAI/bge-m3 · MIT | dense + sparse + multi-vector multilingual retrieval | `layer5_retrieval/embeddings.py`, `repository.index_embeddings`, `Executor.search_passages`; `ingest_store --embeddings`, `RETRIEVAL_MODE` | implemented, executed (VM, CPU), **evaluated** (EXPERIMENTS §2); not in Docker image | dense doc-recall@10 0.98 / MRR 0.88 vs lexical 0.28 / 0.23 | pretrained model used as published (no fine-tuning); doc-level relevance only |
| 9 | BGE reranker v2-m3 | huggingface.co/BAAI/bge-reranker-v2-m3 · Apache-2.0 | cross-encoder reranking | `embeddings.BGEReranker`, `RETRIEVAL_MODE=hybrid_rerank` (top 20) | implemented, executed, evaluated | +0.04 nDCG over hybrid, still below dense alone; ~4.7 s/query CPU | CPU latency |
| 10 | pgvector | github.com/pgvector/pgvector · PostgreSQL licence | vector storage in Postgres | migration 0002 (`dense_vec vector(1024)`), `repository.dense_search` (`<=>` cosine) | implemented, executed (VM + tests), compose `db` image switched | 354 passages, exact search | python-cosine fallback on SQLite / plain Postgres |
| 11 | Reciprocal Rank Fusion (Cormack 2009) | — | rank fusion | `Executor.search_passages` (lexical + dense + sparse + ColBERT, k=60) | implemented, executed, evaluated | hybrid RRF below dense alone on this set | unweighted fusion dilutes the strong dense list |
| 12 | VeriFact (Chung et al. 2025) | github.com/philipchung/verifact · MIT | claim decomposition + EHR retrieval + LLM judge | Phase 3 | planned | false-support rate | — |
| 13 | FactEHR (Munnangi et al. 2024/25) | github.com/som-shahlab/factehr · no licence file; data restricted (MIMIC etc.) | fact decomposition + entailment eval | Phase 3 (method only) | planned; dataset **blocked** | — | — |
| 14 | MedFactEval (Grolleau et al. 2025) | github.com/fcgrolleau/medfacteval · MIT | key-fact coverage/contradiction eval | Phase 3/7 | planned | omission recall | — |
| 15 | ArchEHR-QA (Soni & Demner-Fushman 2025) | aclanthology.org/2025.bionlp-1.34 (PhysioNet, credentialed) | evidence-grounded EHR QA benchmark | evaluation design only | dataset **blocked** (credentialed access) | — | — |
| 16 | FHIR R4 / HL7 Austria / ELGA CDA | hl7.org/fhir/R4, fhir.hl7.at | interoperability | Phase 4 | planned | profile validation | validator needs Java |
| 17 | FHIR-Ontop-OMOP (Xiao et al. 2022, JBI) | — | virtual KG over OMOP | Phase 4 adaptation only | **not reproduced** (no OMOP DB) | — | — |
| 18 | ReAct (Yao et al. 2023) | react-lm.github.io | bounded reason/act loop | Phase 5 (`layer4_planner`) | planned | tool-selection accuracy | — |
| 19 | MedAlign (Fleming et al.) | PubMed 41584261; data via Stanford (restricted) | clinician instruction eval | Phase 5/7 eval design | dataset **blocked** | — | — |
| 20 | EHRSQL (Lee et al. 2022) | github.com/glee4810/EHRSQL · CC-BY-4.0 (MIMIC-based data credentialed) | temporal + unanswerable question taxonomy | Phase 5 eval design (synthetic analogues) | planned | abstention | no free-SQL generation by design |
| 21 | MedAgentBench (Jiang et al. 2025) | github.com/stanfordmlgroup/MedAgentBench · MIT | FHIR agent benchmark | Phase 5 | planned (requires its FHIR server) | — | — |
| 22 | TIMER (Cui et al. 2025, npj Digit Med) | — | temporal instruction tuning | Phase 5 | **not reproduced** (training run; no data/GPU) | temporal tests only | — |
