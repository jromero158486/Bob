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
| 3 | GERNERMED++ (Frei, Frei-Stuber, Kramer 2023) | github.com/frankkramer-lab/GERNERMED-pp · **no licence file** (preprint CC BY-NC-SA) | German medication NER (Drug, Strength, Route, Form, Dosage, Frequency, Duration) | `layer2_extraction/ner/gernermed.py` (isolated spaCy 3.2 subprocess) | implemented, executed (VM); disabled in Docker | Phase 1 ablation | licence unclear → not redistributed |
| 4 | BioC (Comeau et al. 2013) | github.com/bionlplab/bioc · MIT | interoperable annotation format | `tools/export_bioc.py` (Phase 1) | see EXPERIMENTS §1 | round-trip offset test | — |
| 5 | CARDIO:DE (Richter-Pechanski et al. 2023) | dataset via application (heiDATA, DUA) | German cardiology letters gold standard | evaluation only | **blocked** (restricted access, not obtained) | — | apply for access |
| 6 | LLM structured extraction (grounded JSON) | Groq `openai/gpt-oss-120b` via OpenAI-compatible API | relation/complex fact extraction with verbatim quotes | `layer2_extraction/llm/structured_extraction.py` + `ingest_store --llm` | implemented, enabled (opt-in), executed | Phase 1 ablation | prompt not tuned; rate limits |
| 7 | Terminology linking (candidate retrieval + rerank) | local ICD-10/ATC/LOINC lexicons | candidate codes, never auto-verified | `layer2_extraction/terminology.py` | Phase 1 | normalization accuracy vs IBM codes | SNOMED CT **blocked** (licence) |
| 8 | BGE-M3 (Chen et al. 2024) | huggingface.co/BAAI/bge-m3 · MIT | dense + sparse + multi-vector multilingual retrieval | Phase 2 (`layer5_retrieval`) | planned | Recall@k, MRR, nDCG | needs torch; CPU-only VM (8 cores, no GPU) |
| 9 | BGE reranker v2-m3 | huggingface.co/BAAI/bge-reranker-v2-m3 · Apache-2.0 | cross-encoder reranking | Phase 2 | planned | ablation | — |
| 10 | pgvector | github.com/pgvector/pgvector · PostgreSQL licence | vector storage in Postgres | Phase 2 | planned | latency | image `pgvector/pgvector` |
| 11 | Reciprocal Rank Fusion (Cormack 2009) | — | rank fusion | `layer5_retrieval/engine.py::op_search_text` | implemented, executed (lexical terms only) | Phase 2 | fuse dense/sparse |
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
