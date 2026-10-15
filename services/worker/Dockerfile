# Asynchronous jobs: outbox relay, approval expiry, evaluation, retention.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 gov

COPY services/worker/pyproject.toml ./
COPY services/worker/src ./src
RUN pip install -e .

USER gov

CMD ["python", "-m", "gov.worker.main"]
