FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
RUN pip install --no-cache-dir -e '.[postgres,api]'
EXPOSE 8000
# Migrate, optionally ingest private data mounted at /data (never baked into the image), then serve.
CMD ["sh", "-c", "python -c 'from backend.app.layer3_store.db import migrate; migrate()' && if [ -d /data ] && [ \"$(ls -A /data 2>/dev/null)\" ]; then python -m backend.app.tools.ingest_store --input /data --no-gernermed; fi && uvicorn backend.app.api.main:app --host 0.0.0.0 --port 8000"]
