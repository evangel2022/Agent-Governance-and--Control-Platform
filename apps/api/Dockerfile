# Control plane image. Secrets are never baked in: they are read from Vault at
# runtime (ADR-0008).
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 gov

COPY apps/api/pyproject.toml ./
COPY apps/api/src ./src
RUN pip install -e .

# The alembic configuration and migrations are added by T017; when they exist,
# copy them here so the image can run `alembic upgrade head` at start-up.

USER gov
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=20 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "gov.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
