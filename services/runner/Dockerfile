# Isolated execution runtime. This image runs untrusted tool code, so it holds
# no database credentials and no ambient cloud identity (ADR-0006).
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 runner

COPY services/runner/pyproject.toml ./
COPY services/runner/src ./src
RUN pip install -e .

USER runner
EXPOSE 9100

CMD ["uvicorn", "gov.runner.app:app", "--host", "0.0.0.0", "--port", "9100"]
