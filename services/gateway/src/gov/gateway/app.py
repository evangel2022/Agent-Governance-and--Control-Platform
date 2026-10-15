"""Gateway HTTP entry point.

The gateway's behaviour lives in `pipeline.py`; this module only exposes the
process. The invocation endpoint is wired when the enforcement chain is
completed (T053); the liveness probe below is what the development stack's
health check and the container image rely on.
"""

from __future__ import annotations

from fastapi import FastAPI

from gov.gateway.pipeline import EnforcementPipeline
from gov.gateway.routes import install


def create_app(pipeline: EnforcementPipeline | None = None) -> FastAPI:
    """Build the gateway application.

    `pipeline` is supplied by the wiring layer once the OPA, Vault and runner
    adapters exist. Until then the process starts, reports that enforcement is
    unavailable, and refuses every invocation rather than allowing one.
    """
    app = FastAPI(
        title="MCP Gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install(app, pipeline)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "enforcement": "configured" if pipeline is not None else "unavailable",
        }

    return app


app = create_app()
