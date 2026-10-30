# Reproducible demo — five IBM scenarios

## A. In the browser (published app)

1. Open https://screenshot-stitchery-studio.lovable.app and check the **Live backend** badge and patient `patient-0000-0001` (8 documents).
2. For each situation in the IBM ZIP's `cases/situations.md`, enter:
   - **Role:** `Anaesthetist` · `Surgeon` · `General practitioner` · `Emergency physician` · `General practitioner`
   - **Task:** the situation's title, a period, then its description, copied verbatim.
3. On each screen, without expanding anything, show: the summary, the first fact blocks, **Potential conflicts**, and **Not documented** (if present). Click one citation to open the original German letter with the exact highlight.
4. Extra views: **Medications** (candesartan 2015 vs 2016), **Timeline**, **Review** (one decision), **Verify clinical statement** with `Patient nimmt ASS. HbA1c 7,9 %. Penicillinallergie.` (expected: supported / contradicted / not addressed).

What to expect, and the known gaps (S4 kidney function, S5 interval): see [JUDGING_RESULTS.md](JUDGING_RESULTS.md).

## B. Scripted (same requests, raw output and link checks)

```bash
python -m venv .venv && .venv/bin/pip install -e .   # once (installs backend deps)
export CLINICAL_API_TOKEN=<demo token>          # from the team, never committed
.venv/bin/python -m evaluation.judging.hosted_ibm_audit \
  --base https://85-217-172-189.sslip.io/api/v1 \
  --cases <ibm-zip>/cases --data <ibm-zip>/data \
  --out artifacts/judging/run \
  [--extra my_new_tasks.json]                   # optional: [{"role": "...", "task": "..."}]
```

Output per task: `S1.json` (raw API payload), `S1.txt` (screen as text: blocks, facts, conflicts, missing items) and `summary.json` (latency, fact count, link count, broken links). Grading against `expected.json` is manual; the script never reads it.

For a local backend instead of Exoscale, start Docker as in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) and use `--base http://localhost:8000/api/v1`.
