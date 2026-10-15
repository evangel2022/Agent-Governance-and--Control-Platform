"""Tests for the runner process entry point (T122)."""

from __future__ import annotations

import httpx

from gov.runner.app import create_app


async def test_runner_liveness_probe() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://runner",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
