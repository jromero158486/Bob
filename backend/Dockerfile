FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
RUN pip install --no-cache-dir -e '.[postgres,api,clinical]'
# GERNERMED++ (spaCy 3.2, unclear licence) is not baked in; ingest reports it as "disabled" in the component list.
EXPOSE 8000
# Windows checkouts may convert line endings; the entrypoint must be LF.
RUN sed -i 's/\r$//' /app/backend/docker-entrypoint.sh && chmod +x /app/backend/docker-entrypoint.sh
CMD ["sh", "backend/docker-entrypoint.sh"]
