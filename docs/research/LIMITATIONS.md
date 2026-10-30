# Limitations

- One synthetic patient (8 documents) from IBM; extra patients are author-written synthetic letters. No real data.
- Lexicons and rules were tuned while looking at the IBM questions; benchmark numbers are not held-out.
- Automatic benchmark checks are string matches, not independent clinical review.
- GERNERMED++ licence is unspecified; it runs only in a separate environment and is not shipped.
- No GPU on the development VM (8 CPU cores, 31 GB RAM); large models run on CPU or the event A5000.
- No authentication / authorisation; demo-only (docs/SECURITY_AND_AUTH.md).
- Restricted datasets (CARDIO:DE, FactEHR, ArchEHR-QA, MedAlign, MIMIC) were not used.

- Phase 2 retrieval is evaluated with document-level relevance on one patient (8 documents); no passage-level gold.
- BGE-M3 / reranker run on the VM only (CPU, `.[retrieval]` extra, ~2.2 GB weights each); the Docker backend image
  does not include torch, so in Docker `RETRIEVAL_MODE` other than `lexical` falls back to lexical and reports a warning.
- Terminology candidate retrieval over a full ICD-10-GM catalogue is not implemented (catalogue not obtained);
  only local-lexicon candidates exist.
