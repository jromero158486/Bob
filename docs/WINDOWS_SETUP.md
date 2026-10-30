# Windows setup (demo laptop)

## Requirements (measured on the running stack, CPU only, no GPU needed)

| Resource | Minimum | Recommended | Measured |
|---|---|---|---|
| RAM for Docker (WSL2) | 6 GB | 8 GB (16 GB laptop) | models service 2.2 GB, backend 0.15 GB, db 0.05 GB |
| Free disk | 15 GB | 20 GB | images: models 2.5 GB, backend 0.7 GB, pgvector 0.6 GB; model weights: BGE-M3 4.3 GB, reranker 2.2 GB, NLI 0.55 GB; database < 0.1 GB; frontend node_modules ~0.5 GB |
| CPU | 4 cores | 8 cores | warmed task 0.8–3 s, verification ~1 s per claim |
| Network | first start only | — | about 7 GB model download into the `hf-cache` volume |

To save 2.2 GB disk and RAM, run without the reranker (`RERANKER=none`). Only the optional `hybrid_rerank` mode needs it.

## Install once

1. Install **Docker Desktop** (WSL2 backend), **Git for Windows** and **Node.js 20 LTS**.
2. Docker Desktop → Settings → Resources: give WSL at least 8 GB of memory. Alternatively, create
   `%UserProfile%\.wslconfig` with:
   ```
   [wsl2]
   memory=8GB
   ```
   then run `wsl --shutdown`.
3. Clone both repos. Keep the IBM data outside them:
   ```powershell
   git clone https://github.com/jromero158486/Bob.git
   git clone https://github.com/jromero158486/screenshot-match.git
   ```
   `Bob/.gitattributes` keeps shell scripts LF, and the backend image strips CRLF from its entrypoint anyway.

## Start (PowerShell)

```powershell
cd Bob
$env:IBM_DATA_DIR = "C:/hackathon/AIM-hack-track1-shipit-main/data"   # folder containing patient-0000-0001; forward slashes
$env:CORS_ORIGINS = "http://localhost:5173,http://localhost:8080"
docker compose up -d --build
```

- **First start:** 15–30 min. It builds the images and downloads the models; the `models` service only reports healthy once they are loaded.
- **Later starts:** about 1 min.

Check:

```powershell
docker compose ps                                    # db, models healthy; backend, frontend up
curl.exe http://localhost:8000/api/health
curl.exe http://localhost:8000/api/v1/patients
docker compose logs backend | Select-String encoded  # "encoded": 354 on first start
```

Frontend:

```powershell
cd ..\screenshot-match
Set-Content .env.local "VITE_CLINICAL_API_BASE_URL=http://localhost:8000/api/v1"
npm install
npx vite dev --port 5173      # open http://localhost:5173, check the "Live backend" badge
```

The legacy backup UI is at http://localhost:8080. It needs no Node.js.

## Do the day before

- Run the first start fully: images built, models downloaded, 354 passages encoded.
- Run each demo task once (see `DEMO_RUNBOOK.md`).
- After that, no internet is needed except for Groq, and Groq is optional: the planner defaults to the rule-based one.

## Stop

`docker compose down`. **Never** add `-v`: it deletes the database and the downloaded models.
