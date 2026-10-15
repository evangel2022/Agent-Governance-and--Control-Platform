"""The permission-surface matrix (T016).

For every route this feature protects, assert the authorization outcome for each
of the five built-in roles and for an unauthenticated caller.

This is the test that catches a dropped guard. It deliberately does not care what
a route returns on success, only whether an unpermitted caller is refused - so it
stays valid as the routes' behaviour changes, and it fails the moment a guard is
removed or a route is added without being covered.

Routes are described as data. A second test asserts that every route the
application declares under the paths this feature owns appears in that data, so
adding a route and forgetting to cover it is a test failure rather than a gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from _surface import OWNED_PREFIXES, SURFACE, resolve
from fastapi import FastAPI

from gov.api.application.permission.assignments import AssignmentService
from gov.api.application.permission.roles import RoleService
from gov.api.application.permission.users import UserService
from gov.api.domain.identity.permissions import (
    AGENT_DEVELOPER,
    AUDITOR,
    BUSINESS_APPROVER,
    PLATFORM_ADMINISTRATOR,
    ROLE_PERMISSIONS,
    SECURITY_COMPLIANCE,
)
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

ALL_ROLES: tuple[str, ...] = (
    PLATFORM_ADMINISTRATOR,
    AGENT_DEVELOPER,
    SECURITY_COMPLIANCE,
    BUSINESS_APPROVER,
    AUDITOR,
)


def _app(*, roles: frozenset[str] | None) -> FastAPI:
    store = InMemoryStore()
    app = create_app(
        user_service=UserService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: "user-1",
        ),
        role_service=RoleService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: "role-1",
        ),
        assignment_service=AssignmentService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: "assignment-1",
        ),
    )
    if roles is not None:
        principal = Principal(
            subject=ACTOR, user_id=ACTOR, organisation_id=ORG, roles=roles
        )

        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = principal
            return await call_next(request)

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.parametrize(("method", "path", "body", "_required"), SURFACE)
async def test_an_unauthenticated_caller_is_refused(
    method: str, path: str, body: dict[str, Any] | None, _required: str
) -> None:
    async with _client(_app(roles=None)) as client:
        response = await client.request(method, resolve(path), json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize(("method", "path", "body", "required"), SURFACE)
async def test_a_role_without_the_permission_is_refused(
    role: str, method: str, path: str, body: dict[str, Any] | None, required: str
) -> None:
    """Whether a role may act is taken from the matrix, not from this test."""
    if required in ROLE_PERMISSIONS[role]:
        pytest.skip(f"{role} holds the permission this route requires")

    async with _client(_app(roles=frozenset({role}))) as client:
        response = await client.request(method, resolve(path), json=body)

    assert response.status_code == 403, f"{role} was not refused on {method} {path}"
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(("method", "path", "body", "_required"), SURFACE)
async def test_a_role_holding_the_permission_is_not_refused(
    method: str, path: str, body: dict[str, Any] | None, _required: str
) -> None:
    """Authorization is what is asserted; the business outcome may be anything."""
    async with _client(_app(roles=frozenset({PLATFORM_ADMINISTRATOR}))) as client:
        response = await client.request(method, resolve(path), json=body)
    assert response.status_code not in (401, 403)


def test_every_declared_route_under_the_owned_paths_is_covered() -> None:
    """A new route that nobody covered is a gap; this turns it into a failure."""
    app = _app(roles=frozenset({PLATFORM_ADMINISTRATOR}))
    declared = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
        and any(route.path.startswith(prefix) for prefix in OWNED_PREFIXES)
    }
    covered = {(method, path) for method, path, _, _ in SURFACE}

    assert declared - covered == set(), (
        "routes declared but not covered by the security matrix: "
        f"{sorted(declared - covered)}"
    )


def test_the_matrix_covers_every_route_it_claims_to() -> None:
    """The other direction: the table must not describe routes that do not exist."""
    app = _app(roles=frozenset({PLATFORM_ADMINISTRATOR}))
    declared = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }
    covered = {(method, path) for method, path, _, _ in SURFACE}

    assert covered - declared == set(), (
        "the matrix covers routes the application does not declare: "
        f"{sorted(covered - declared)}"
    )
