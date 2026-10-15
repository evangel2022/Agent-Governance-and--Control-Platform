"""Runner HTTP entry point.

The runner executes tool adapters on behalf of the gateway. This module exposes
the process and its liveness probe; the sandbox classes, adapter interface and
gateway-identity check are the behaviour specified by T052.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the runner application."""
    app = FastAPI(
        title="Tool Runner",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
