# Experiments

Every result records: commit, model versions, data split, configuration, execution status, metrics.
Generated outputs go to `artifacts/research/` (gitignored). Scripts live in `evaluation/research/`.

## §0 Baseline (commit 87c4089)
- Tests: 66 passed, 2 skipped (`.venv/bin/python -m pytest -q`).
- Data: IBM patient-0000-0001 (8 docs; tuning data, not held out) + 10 author-written tasks (private file).
- Config A (heuristic planner, rules-de + native ConText + medSpaCy sections + GERNERMED++):
  IBM 15 key terms 57/61, exact values in supported claims 27/28; new tasks 23/23; all citations integrity-valid;
  median 0.5 s per task.
- Config B (Groq `openai/gpt-oss-120b` planner + LLM extraction): new tasks 22/23 values; IBM situation 2 shows
  ~20 review-only (LLM) claims per question; median 12.7 s.
- Details and caveats: `docs/RELIABILITY_PASS.md`.
