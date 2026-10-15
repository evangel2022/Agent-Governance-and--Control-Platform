"""Response shapes for the three refusal outcomes (T038).

The outcome matters, and so does the shape: a caller has to be able to tell
"you may not" from "we could not decide", and both from "you are not signed in".
Every refusal is a problem document with a stable code.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from _harness import (
    PERMISSION_SURFACE,
    REGISTRY_SURFACE,
    permission_app,
    registry_app,
    resolve_path,
)

PROBLEM = "application/problem+json"


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.parametrize(("method", "path", "body"), PERMISSION_SURFACE)
async def test_an_unauthenticated_request_is_401_with_a_problem_body(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    app, _ = permission_app(authenticate=False)
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM)
    payload = response.json()
    assert payload["code"] == "unauthorized"
    assert payload["status"] == 401
    assert payload["title"]


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_SURFACE)
async def test_an_unauthenticated_registry_request_is_401(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    app, _ = registry_app(authenticate=False)
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_SURFACE)
async def test_a_caller_without_the_permission_is_403_with_a_reason(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """No assignment at all means no permission at all."""
    app, _ = registry_app(role_code="")
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM)
    payload = response.json()
    assert payload["code"] == "forbidden"
    assert payload["detail"]


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_SURFACE)
async def test_unwired_components_fail_closed_as_503(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """A deployment without a decision component must refuse, not permit."""
    app, _ = registry_app(wire_components=False)
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["code"] == "service_unavailable"
