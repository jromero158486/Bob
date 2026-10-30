# Demo runbook (synthetic IBM patient, local laptop)

## 1. Start (about 3 min on a fresh volume, about 1 min on a restart)

```sh
# backend: Postgres+pgvector, BGE-M3/reranker/NLI model service, FastAPI (+ legacy UI on :8080)
cd Bob
IBM_DATA_DIR=<ibm>/data HF_CACHE_DIR=~/.cache/huggingface \
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080 \
docker compose up -d
curl -s localhost:8000/api/health          # status ok, database postgresql
curl -s localhost:8000/api/v1/patients     # patient-0000-0001, 8 documents

# Lovable frontend (repo screenshot-match)
echo 'VITE_CLINICAL_API_BASE_URL=http://localhost:8000/api/v1' > .env.local
npm install && npx vite dev --port 5173    # open http://localhost:5173
```

Check before presenting: the result header shows the **Live backend** badge, not "Synthetic fixture".
The first BGE-M3 model download is about 4.5 GB, so warm the Hugging Face cache before the demo.

## 2. Demo script (each step takes about 1 s)

1. German, anaesthetist: role `Anästhesistin`, task `Präoperative Abklärung: Allergien, Antikoagulation, Raucherstatus und relevante Herzbefunde?`
   - Show: Thrombo ASS only; contrast-medium allergy; EF 60%; **Not documented: smoking status** (with the list of searched documents).
   - Show: the 8 record conflicts (BMI, carotid side, discharge date "20156").
   - Click a citation to open the original German letter with the exact span highlighted.
2. English, oncology nurse: `What is the planned breast cancer treatment and when, and what are the receptor status and Ki-67?`
   - Shows: quadrantectomy + IORT on 16.05.2016; ER/PR positive, HER2 negative, Ki-67 20%, each with a source.
3. Medications page: Blopress 1-0-1/2 (2015) vs 1-0-1 (2016). Review page: approve one conflict.
4. Optional: **Verify clinical statement** with
   `Die Patientin nimmt Thrombo ASS 100 mg 1-0-0. Das HbA1c lag zuletzt bei 7,9 %. Die Patientin hat eine Penicillinallergie.`
   - Expected: supported / contradicted (source says 6,4 %) / not addressed → review. Takes about 1–2 s.
   - Say: "supported" means the claim is backed by the cited record text. It is not clinical verification.

## 3. What the architecture slide can claim

- Main flow: rule planner → structured facts + BGE-M3 dense passage search → strict citation integrity +
  value/negation checks + conflict detection.
- The optional NLI verification runs only on request.
- Each response reports which planner and retrieval mode actually ran, and any fallback.
- Numbers: `docs/SCIENTIFIC_REPORT.md`.

## 4. If something fails

| Symptom | Action |
|---|---|
| UI shows "Backend unreachable" | `docker compose ps`; `curl localhost:8000/api/health`; check `CORS_ORIGINS` includes the UI origin |
| `retrieval_warnings`: lexical fallback | the model service is still loading (`docker compose logs models`); answers still work (structured + keyword) |
| 502 on :8080 after a backend restart | already fixed (nginx re-resolves the backend); otherwise `docker compose restart frontend` |
| Slow or failed verification | use `judge: "none"` (deterministic checks only) or skip the optional step |
| Groq unavailable | not needed: the planner is the rule planner by default (`PLANNER=heuristic`) |

Stop: `docker compose down`. **Never** use `-v` unless you want to re-ingest and re-index.
