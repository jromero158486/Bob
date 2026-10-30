# Hosted demo on one Exoscale VM

Synthetic IBM data only. The local Docker demo (`docs/DEMO_RUNBOOK.md`) stays the primary backup.

## Shape
- One Ubuntu 24.04 **Standard Large** instance (4 vCPU, 8 GB RAM), 50 GB local disk, zone `at-vie-1`.
- Measured use: model service (BGE-M3 + NLI) ~2.2 GB RAM, rest < 0.3 GB. `RERANKER=none` (unused in the demo).
- Security group: 80/443 from anywhere (Caddy), 22 only from operator IPs. Nothing else is published.
- Caddy terminates HTTPS (Let's Encrypt, hostname `<ip-with-dashes>.sslip.io` unless a domain is set) and forwards
  **only** `/api/v1/*` and `/api/health` to FastAPI. PostgreSQL, the model service, FastAPI and the legacy UI are
  reachable only on the internal Docker network.
- FastAPI enforces `DEMO_API_TOKEN` (Bearer) on every `/api` route except health, and `CORS_ORIGINS` limits browser
  calls to the published Lovable origin. This is a demo gate, not user authentication: the token ships in the
  public Lovable bundle. Real hospital use needs the boundary in `docs/SECURITY_AND_AUTH.md`.
- Persistent data: Docker volumes `pgdata`, `hf-cache` (~5 GB with RERANKER=none), `caddy-data`; IBM data in
  `/srv/lumen/data` (read-only mount). All on the instance disk; take an Exoscale snapshot after first start.

## Cost (Exoscale list price, EUR, excl. VAT, checked on deploy day)
Standard Large €0.09333/h + 50 GB × €0.00014/GiB·h ≈ €0.10/h ≈ **€2.40/day, ~€72/month**. Stop or delete the
instance after judging (a stopped instance still pays for its disk, ~€0.17/day).

## Deploy (on the VM, from the repo root)
```bash
sudo mkdir -p /srv/lumen/data   # copy the patient-* folders here (scp/rsync); never commit them
cp deploy/exoscale/env.example deploy/exoscale/.env && chmod 600 deploy/exoscale/.env   # then edit values
docker compose -f docker-compose.yml -f deploy/exoscale/docker-compose.cloud.yml \
  --env-file deploy/exoscale/.env up -d --build
curl -s https://$DOMAIN/api/health
curl -s -H "Authorization: Bearer $DEMO_API_TOKEN" https://$DOMAIN/api/v1/patients
```
First start downloads ~5 GB of models (several minutes on Exoscale bandwidth); later restarts reuse the volume.

## Current deployment
- Instance `lumen-demo` (standard.large, 50 GiB, at-vie-1), security group `lumen-demo` (443/80 public, 22 operator
  IP only), public URL `https://85-217-172-189.sslip.io/api/v1` (health: `/api/health`).
- Lovable production build reads `.env.production` in the frontend repo (base URL + demo token).
- Operations (SSH as `ubuntu`, repo in `~/lumen`):
  `docker compose -f docker-compose.yml -f deploy/exoscale/docker-compose.cloud.yml --env-file deploy/exoscale/.env ps|logs|restart`.
- Stop after judging: `exo compute instance stop lumen-demo -z at-vie-1` (or `delete`).

## Lovable
Set in the Lovable project (build-time env) and republish:
```
VITE_CLINICAL_API_BASE_URL=https://<DOMAIN>/api/v1
VITE_CLINICAL_API_TOKEN=<DEMO_API_TOKEN>
```
Rotate the token (edit `.env`, `up -d backend`, update Lovable) if it leaks beyond the team and judges.
