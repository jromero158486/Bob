# Connecting the Lovable frontend to the real backend

The Lovable app must call the FastAPI backend, never fixed mock data. The contract is `docs/openapi.json`
(TypeScript types: `frontend/src/api/schema.ts`). It is versioned (`api_version` in `GET /api/health`) and changes
only by adding fields or endpoints.

| Lovable screen | Endpoint |
|---|---|
| Patient picker | `GET /api/patients` |
| Free-text task (any role, German or English) | `POST /api/tasks` `{patient_id, request, retrieval_mode?}` → sections/claims with `citations`, `conflicts`, `missing`, `timeline`, `provenance` (planner, `retrieval_used`, `retrieval_warnings`), `timings_ms` |
| Citation click → original passage | `GET /api/patients/{pid}/documents/{document_id}`; highlight the passage whose `passage_id` matches the citation (`quote` is the exact cited text) |
| Conflicts panel | `GET /api/patients/{pid}/conflicts` (also inside each task response) |
| Review buttons | `GET/POST /api/patients/{pid}/review` |
| Check a draft text (optional) | `POST /api/verify` `{patient_id, text, judge: "nli"|"none"|"groq"}` → atomic claims with verdict, `needs_review`, evidence citations; `clinically_verified` is always false |

Rules for the UI: show `missing` ("not documented") separately from documented negatives; show `status` and
`citation_integrity` per claim; show `provenance.planner.name == "heuristic-fallback"` and any `retrieval_warnings`.

## Running it for the demo

The backend has no authentication and binds to 127.0.0.1 (synthetic data only). For a Lovable app running in the
browser on the demo laptop:

```sh
CORS_ORIGINS="http://localhost:8080,https://<your-app>.lovable.app" DEMO_API_TOKEN=<random> \
IBM_DATA_DIR=<ibm>/data HF_CACHE_DIR=~/.cache/huggingface docker compose up -d
```

Set the Lovable API base URL to `http://localhost:8000` (the browser on the demo machine reaches its own loopback).
If `DEMO_API_TOKEN` is set, send it as the `X-Demo-Token` header. Do not expose port 8000 publicly. If a public
tunnel is unavoidable for the demo, set `DEMO_API_TOKEN` first.
