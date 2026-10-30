FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
RUN pip install --no-cache-dir -e '.[postgres,api,clinical]'
# GERNERMED++ (spaCy 3.2, unclear licence) is not baked in; ingest reports it as "disabled" in the component list.
EXPOSE 8000
CMD ["sh", "backend/docker-entrypoint.sh"]
