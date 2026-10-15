"""Deny by default, proven rather than assumed (T041, FR-008, FR-017).

Three ways of holding nothing: no assignment, a permission name the catalogue
does not recognise, and a role nobody is assigned. Each must grant nothing, and
the refusals must come from the decision rather than from a missing code path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from _harness import ACTOR, ORG, REGISTRY_SURFACE, registry_app, resolve_path
from _inmemory import InMemoryAuthorizationEngine

from gov.api.application.ports import (
    RoleAssignmentRecord,
    RolePermissionRecord,
    RoleRecord,
)


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    )


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_SURFACE)
async def test_a_caller_with_no_assignments_can_do_nothing(
    method: str, path: str, body: dict | None
) -> None:
    app, _ = registry_app(role_code="")
    async with _client(app) as client:
        response = await client.request(method, resolve_path(path), json=body)
    assert response.status_code == 403


async def test_an_unknown_permission_name_grants_nothing() -> None:
    """FR-008: a name the catalogue does not recognise is not trusted."""
    app, store = registry_app(role_code="")
    store.roles["role-custom"] = RoleRecord(
        id="role-custom",
        organisation_id=ORG,
        code=None,
        name="custom",
        description="A role with one invented permission.",
    )
    granted_at = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
    store.bindings["invented"] = RolePermissionRecord(
        id="invented",
        organisation_id=ORG,
        role_id="role-custom",
        permission_name="registry.teleport",
        granted_by=ACTOR,
        granted_at=granted_at,
    )
    store.assignments["a-custom"] = RoleAssignmentRecord(
        id="a-custom",
        organisation_id=ORG,
        user_id=ACTOR,
        role_id="role-custom",
        scope_type="organisation",
        granted_by=ACTOR,
        granted_at=granted_at,
    )
    resolver = app.state.permission_resolver
    resolver.invalidate(ORG)

    # The binding exists; the resolver still grants nothing, because the name is
    # not in the catalogue.
    assert resolver.resolve(organisation_id=ORG, user_id=ACTOR) == frozenset()


async def test_an_unknown_role_grants_nothing() -> None:
    app, store = registry_app()
    assignment = store.assignments["builtin-assignment-platform_administrator"]
    assignment.role_id = "role-that-does-not-exist"
    app.state.permission_resolver.invalidate(ORG)

    async with _client(app) as client:
        response = await client.get("/v1/agents")
    assert response.status_code == 403


async def test_the_refusal_names_what_was_missing() -> None:
    app, _ = registry_app(role_code="")
    async with _client(app) as client:
        response = await client.get("/v1/agents")

    payload = response.json()
    assert payload["code"] == "forbidden"
    assert "registry.read" in payload["errors"][0]["message"]


async def test_a_decision_is_still_asked_for_when_nothing_is_held() -> None:
    """Deny-by-default belongs to the decision component, not to the guard."""
    engine = InMemoryAuthorizationEngine()
    app, _ = registry_app(role_code="", engine=engine)
    async with _client(app) as client:
        await client.get("/v1/agents")

    assert engine.seen, "the guard decided for itself instead of asking"
    assert engine.seen[0]["permissions"] == []
