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

## §1a German ConText/NegEx (`python -m evaluation.research.phase1_context`)
Data: `evaluation/research/data/context_de.jsonl`, 40 author-written synthetic sentences (14 negated, 7 possible,
8 historical/future, 5 family). Written before looking at the engine output; not clinician-annotated.
Rules `de-context-0.1`, commit of the run is stored in `artifacts/research/phase1_context.json`.

| engine | negation P/R/F1 | possible R | temporality R | family R | all 4 attributes correct | time (40 sents) |
|---|---|---|---|---|---|---|
| native (default) — before rule changes | 1.00 / 0.79 / 0.88 | 0.57 | 1.00 | 0.80 | 33/40 | 3 ms |
| medSpaCy ConText, same rules — before | 1.00 / 0.79 / 0.88 | 0.43 | 0.63 | 0.80 | 29/40 | 936 ms |
| native, rules `de-context-0.2` (tuned on this set — not held out) | 1.00 / 1.00 / 1.00 | 1.00 | 1.00 | 1.00 | 40/40 | 1 ms |
| medSpaCy, `de-context-0.2` (same set) | 1.00 / 1.00 / 1.00 | 0.86 | 0.63 | 1.00 | 36/40 | 647 ms |

**Held-out set** `context_de_heldout.jsonl` (30 sentences written after the 0.2 rule change, rules not adjusted
afterwards; 10 negated, 6 possible, 6 temporal, 4 family):

| engine (`de-context-0.2`) | negation P/R/F1 | possible P/R | temporality P/R | family P/R | all correct |
|---|---|---|---|---|---|
| native | 1.00 / 0.80 / 0.89 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 0.75 | 27/30 |
| medSpaCy ConText | 1.00 / 0.80 / 0.89 | 1.00 / 0.83 | 1.00 / 0.83 | 1.00 / 0.75 | 25/30 |

Held-out errors: "nicht auskultierbar", "fehlen" (post-posed negation verbs not in rules), "Großmutter" (relative
not in the family list). These are left unfixed so the held-out numbers stay honest.

Failure analysis (both engines): post-posed negation ("wurde nicht beobachtet/festgestellt"), verb negation
("verneint"), hedges ("am ehesten", "möglicherweise", "nicht auszuschließen"), negated family history. medSpaCy
additionally misses `Z.n.`, `St.p.`, `Vd.a.` (spaCy's German tokenizer splits the abbreviations, so its token-aligned
matcher drops them) — the reason the native engine is the default.
