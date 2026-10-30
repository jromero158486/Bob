# Models, dependencies and licences

| Item | Version used | Licence (checked via GitHub/HF API) | Where it runs | Redistributed? |
|---|---|---|---|---|
| spaCy | 3.7.5 (main env) | MIT | main venv, Docker | via pip |
| medSpaCy | 1.3.1 | MIT | main venv, Docker | via pip |
| GERNERMED++ `de_GERNERMEDpp_GottBERT` | 1.0.0 (spaCy 3.2.3, Python 3.10 env) | repository has no licence file; preprint CC BY-NC-SA | separate venv (`GERNERMED_PYTHON`) | **no** (download yourself) |
| Groq `openai/gpt-oss-120b` | API, temperature 0 | Apache-2.0 weights; Groq ToS for API | remote API, key from env only | n/a |
| bioc (Python) | see pyproject | MIT | main venv | via pip |
| BAAI/bge-m3 (rev 5617a9f61b02) via FlagEmbedding 1.3.5, torch 2.15.0+cpu, transformers 4.49.0 | Phase 2 — executed | MIT | VM CPU (8 cores, fp32) | HF cache; not baked into Docker (`.[retrieval]` extra) |
| BAAI/bge-reranker-v2-m3 (rev 953dc6f6f85a) via FlagEmbedding 1.3.5 | Phase 2 — executed | Apache-2.0 | VM CPU (fp32) | HF cache; not in Docker |
| pgvector (image `pgvector/pgvector:pg16`) | Phase 2 — executed | PostgreSQL licence | Postgres | compose `db` image; migration 0002 adds `dense_vec vector(1024)` only when the extension is available |
| ICD-10 / ATC / LOINC subsets | hand-curated lexicons in `layer2_extraction/resources` | WHO ICD-10 categories, WHO ATC codes, LOINC (Regenstrief licence, codes only) | repo | codes only |
| SNOMED CT | — | Affiliate licence required (Austria is a member, national release licence needed) | **blocked** | no |

Data: IBM synthetic patient data stays outside the repo (mounted read-only). CARDIO:DE, FactEHR, ArchEHR-QA, MedAlign
and MIMIC-based EHRSQL data were **not** obtained; no results are reported on them.
