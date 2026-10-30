#!/bin/sh
# Migrate, ingest private data mounted read-only at /data (never baked into the image), then serve.
# /data may be one patient directory (has documents/) or a directory of patient-* directories.
set -e
python -c 'from backend.app.layer3_store.db import migrate; migrate()'
ingest() { python -m backend.app.tools.ingest_store --input "$1" --no-gernermed --section-engine medspacy $INGEST_FLAGS; }
if [ -d /data/documents ]; then
  echo "refusing /data: mount the parent of patient-* directories so patient identity comes from the directory name" >&2
  exit 1
fi
for d in /data/patient-*; do [ -d "$d" ] && ingest "$d"; done
exec uvicorn backend.app.api.main:app --host 0.0.0.0 --port 8000
