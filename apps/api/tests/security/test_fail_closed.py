"""Fail-closed behaviour when the decision component is unavailable (T040, SC-009).

The property under test is narrow and important: an outage is never reported as
a permission. Every protected registry route refuses with 503 - not 403, which
would look like a decision - and the refusal is a problem document. When the
component recovers, the same request succeeds.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from _harness import REGISTRY_SURFACE, registry_app, resolve_path
from _inmemory import InMemoryAuthorizationEngine


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_SURFACE)
async def test_every_protected_route_refuses_when_the_engine_is_down(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    app, _ = registry_app(engine=InMemoryAuthorizationEngine(fail=True))
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)

    assert response.status_code == 503, f"{method} {path} did not fail closed"
    assert response.json()["code"] == "service_unavailable"


async def test_the_refusal_is_not_reported_as_a_permission_decision() -> None:
    """403 would mean "you may not"; 503 means "we could not decide"."""
    app, _ = registry_app(engine=InMemoryAuthorizationEngine(fail=True))
    async with _client(app) as client:
        response = await client.get("/v1/agents")
    assert response.status_code != 403
    assert "could not be obtained" in response.json()["detail"]


async def test_service_resumes_when_the_engine_recovers() -> None:
    app, _ = registry_app()
    async with _client(app) as client:
        recovered = await client.get("/v1/agents")

    assert recovered.status_code == 200


async def test_no_registry_write_succeeds_while_the_engine_is_down() -> None:
    """The guarantee is about writes: none may slip through during an outage."""
    app, store = registry_app(engine=InMemoryAuthorizationEngine(fail=True))
    async with _client(app) as client:
        await client.post(
            "/v1/agents", json={"name": "ap-reconciler", "owner_user_id": "user-1"}
        )

    assert store.agents == {}
