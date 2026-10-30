# Models, dependencies and licences

| Item | Version used | Licence (checked via GitHub/HF API) | Where it runs | Redistributed? |
|---|---|---|---|---|
| spaCy | 3.7.5 (main env) | MIT | main venv, Docker | via pip |
| medSpaCy | 1.3.1 | MIT | main venv, Docker | via pip |
| GERNERMED++ `de_GERNERMEDpp_GottBERT` | 1.0.0 (spaCy 3.2.3, Python 3.10 env) | repository has no licence file; preprint CC BY-NC-SA | separate venv (`GERNERMED_PYTHON`) | **no** (download yourself) |
| Groq `openai/gpt-oss-120b` | API, temperature 0 | Apache-2.0 weights; Groq ToS for API | remote API, key from env only | n/a |
| bioc (Python) | see pyproject | MIT | main venv | via pip |
| BAAI/bge-m3 | Phase 2 | MIT | CPU / A5000 | via HF download |
| BAAI/bge-reanker-v2-m3 | Phase 2 | Apache-2.0 | CPU / A5000 | via HF download |
| pgvector | Phase 2 | PostgreSQL licence | Postgres image | image |
| ICD-10 / ATC / LOINC subsets | hand-curated lexicons in `layer2_extraction/resources` | WHO ICD-10 categories, WHO ATC codes, LOINC (Regenstrief licence, codes only) | repo | codes only |
| SNOMED CT | — | Affiliate licence required (Austria is a member, national release licence needed) | **blocked** | no |

Data: IBM synthetic patient data stays outside the repo (mounted read-only). CARDIO:DE, FactEHR, ArchEHR-QA, MedAlign
and MIMIC-based EHRSQL data were **not** obtained; no results are reported on them.
