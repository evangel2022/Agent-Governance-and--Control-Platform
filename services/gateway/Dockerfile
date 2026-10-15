# MCP gateway image: the single enforcement point for tool invocation.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 gov

COPY services/gateway/pyproject.toml ./
COPY services/gateway/src ./src
RUN pip install -e .

USER gov
EXPOSE 9000

HEALTHCHECK --interval=10s --timeout=5s --retries=20 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:9000/healthz')"

CMD ["uvicorn", "gov.gateway.app:app", "--host", "0.0.0.0", "--port", "9000"]
