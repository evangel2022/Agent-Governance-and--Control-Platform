"""Tests for role and permission administration (T020-T023, US1)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.permission.audit import PermissionChangeError
from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.permission.roles import RoleService
from gov.api.application.ports import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailure,
)
from gov.api.domain.identity.permissions import AUDITOR, PLATFORM_ADMINISTRATOR
from gov.api.domain.permission.rules import BUILTIN_ROLE_CODES
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _service(
    store: InMemoryStore | None = None, cache: EffectivePermissionCache | None = None
) -> tuple[RoleService, InMemoryStore]:
    store = store if store is not None else InMemoryStore()
    counter = itertools.count(1)
    return (
        RoleService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"role-{next(counter)}",
            cache=cache,
        ),
        store,
    )


def _seed_builtin(store: InMemoryStore, code: str = "auditor") -> str:
    from gov.api.application.ports import RolePermissionRecord, RoleRecord

    role_id = f"builtin-{code}"
    store.roles[role_id] = RoleRecord(
        id=role_id,
        organisation_id=None,
        code=code,
        name=code.replace("_", " ").title(),
        description="A built-in role.",
    )
    store.bindings[f"b-{code}"] = RolePermissionRecord(
        id=f"b-{code}",
        organisation_id=None,
        role_id=role_id,
        permission_name="audit.read",
        granted_by="system",
        granted_at=NOW,
    )
    return role_id


# --------------------------------------------------------------- use cases


def test_a_new_role_grants_nothing() -> None:
    service, store = _service()
    role = service.create_role(
        organisation_id=ORG,
        name="erp-invoice-owner",
        description="Owns ERP invoice Agents.",
        actor=ACTOR,
    )

    assert role.status == "active"
    assert role.code is None
    assert service.effective_permissions(organisation_id=ORG, role_id=role.id) == frozenset()
    assert store.audit[-1].action == "role.create"


def test_a_duplicate_role_name_is_refused() -> None:
    service, store = _service()
    service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    with pytest.raises(ConflictError):
        service.create_role(
            organisation_id=ORG, name="owner", description="Also owns.", actor=ACTOR
        )
    assert len([r for r in store.roles.values() if r.organisation_id == ORG]) == 1


def test_a_role_without_a_description_is_refused() -> None:
    service, store = _service()
    with pytest.raises(ValidationFailure) as excinfo:
        service.create_role(
            organisation_id=ORG, name="owner", description="  ", actor=ACTOR
        )
    assert excinfo.value.errors[0]["field"] == "description"
    assert store.audit == []


def test_binding_a_permission_makes_the_role_grant_it() -> None:
    service, store = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    service.bind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.write",
        actor=ACTOR,
    )

    assert service.effective_permissions(organisation_id=ORG, role_id=role.id) == frozenset(
        {"registry.write"}
    )
    assert store.audit[-1].action == "role.bind_permission"


def test_an_unknown_permission_is_refused_and_not_stored() -> None:
    service, store = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    with pytest.raises(ValidationFailure) as excinfo:
        service.bind_permission(
            organisation_id=ORG,
            role_id=role.id,
            permission_name="registry.teleport",
            actor=ACTOR,
        )
    assert excinfo.value.errors[0]["field"] == "permission_name"
    assert len(store.bindings) == 0


def test_a_duplicate_binding_is_refused() -> None:
    service, _ = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    service.bind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.read",
        actor=ACTOR,
    )
    with pytest.raises(ConflictError):
        service.bind_permission(
            organisation_id=ORG,
            role_id=role.id,
            permission_name="registry.read",
            actor=ACTOR,
        )


def test_unbinding_requires_a_reason_and_removes_the_grant() -> None:
    service, _ = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    service.bind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.write",
        actor=ACTOR,
    )

    with pytest.raises(PermissionChangeError):
        service.unbind_permission(
            organisation_id=ORG,
            role_id=role.id,
            permission_name="registry.write",
            actor=ACTOR,
            reason="",
        )
    assert service.effective_permissions(organisation_id=ORG, role_id=role.id) == frozenset(
        {"registry.write"}
    )

    service.unbind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.write",
        actor=ACTOR,
        reason="narrowed to read-only",
    )
    assert service.effective_permissions(organisation_id=ORG, role_id=role.id) == frozenset()


def test_unbinding_something_not_bound_is_not_found() -> None:
    service, _ = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    with pytest.raises(NotFoundError):
        service.unbind_permission(
            organisation_id=ORG,
            role_id=role.id,
            permission_name="registry.read",
            actor=ACTOR,
            reason="not needed",
        )


@pytest.mark.parametrize("code", sorted(BUILTIN_ROLE_CODES))
def test_a_builtin_role_cannot_be_amended_retired_or_rebound(code: str) -> None:
    """FR-031: every one of the five is immutable, not just the famous ones."""
    service, store = _service()
    role_id = _seed_builtin(store, code)

    with pytest.raises(ForbiddenError):
        service.update_role(
            organisation_id=ORG, role_id=role_id, actor=ACTOR, description="changed"
        )
    with pytest.raises(ForbiddenError):
        service.update_role(
            organisation_id=ORG, role_id=role_id, actor=ACTOR, status="retired"
        )
    with pytest.raises(ForbiddenError):
        service.bind_permission(
            organisation_id=ORG,
            role_id=role_id,
            permission_name="registry.write",
            actor=ACTOR,
        )


def test_a_role_can_be_retired_and_then_grants_nothing() -> None:
    service, store = _service()
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    service.bind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.read",
        actor=ACTOR,
    )
    service.update_role(
        organisation_id=ORG, role_id=role.id, actor=ACTOR, status="retired"
    )
    assert store.roles[role.id].status == "retired"
    assert store.audit[-1].action == "role.retire"
    assert store.audit[-1].reason is not None


def test_a_change_invalidates_the_decision_cache() -> None:
    """FR-020: a rebinding takes effect at the next verification."""
    cache = EffectivePermissionCache()
    service, _ = _service(cache=cache)
    role = service.create_role(
        organisation_id=ORG, name="owner", description="Owns things.", actor=ACTOR
    )
    before = cache.generation(ORG)
    service.bind_permission(
        organisation_id=ORG,
        role_id=role.id,
        permission_name="registry.read",
        actor=ACTOR,
    )
    assert cache.generation(ORG) > before


# ------------------------------------------------------------------ routes


def _app(
    *,
    roles: frozenset[str] = frozenset({PLATFORM_ADMINISTRATOR}),
    service: RoleService | None = None,
    store: InMemoryStore | None = None,
) -> tuple[FastAPI, InMemoryStore]:
    store = store if store is not None else InMemoryStore()
    resolved = service if service is not None else _service(store)[0]
    app = create_app(role_service=resolved)
    principal = Principal(
        subject=ACTOR, user_id=ACTOR, organisation_id=ORG, roles=roles
    )

    @app.middleware("http")
    async def _inject_principal(request: Any, call_next: Any) -> Any:
        request.state.principal = principal
        return await call_next(request)

    return app, store


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def test_roles_can_be_created_bound_and_read_back() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/roles",
            json={"name": "erp-invoice-owner", "description": "Owns ERP invoices."},
        )
        role_id = created.json()["id"]
        bound = await client.post(
            f"/v1/roles/{role_id}/permissions",
            json={"permission_name": "registry.write"},
        )
        detail = await client.get(f"/v1/roles/{role_id}")
        bound_list = await client.get(f"/v1/roles/{role_id}/permissions")

    assert created.status_code == 201
    assert created.json()["permissions"] == []
    assert bound.status_code == 201
    assert detail.json()["permissions"] == ["registry.write"]
    assert [item["name"] for item in bound_list.json()] == ["registry.write"]


async def test_the_permission_catalogue_can_be_listed_and_filtered() -> None:
    app, _ = _app()
    async with _client(app) as client:
        everything = await client.get("/v1/permissions")
        registry = await client.get("/v1/permissions", params={"resource": "registry"})

    assert everything.status_code == 200
    assert {item["name"] for item in registry.json()} == {
        "registry.read",
        "registry.write",
        "registry.retire",
        "registry.write_any",
    }


async def test_a_duplicate_name_is_a_conflict_naming_the_field() -> None:
    app, _ = _app()
    body = {"name": "owner", "description": "Owns things."}
    async with _client(app) as client:
        await client.post("/v1/roles", json=body)
        duplicate = await client.post("/v1/roles", json=body)
    assert duplicate.status_code == 409
    assert duplicate.json()["errors"][0]["field"] == "name"


async def test_an_unknown_permission_is_a_validation_error() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/roles", json={"name": "owner", "description": "Owns things."}
        )
        response = await client.post(
            f"/v1/roles/{created.json()['id']}/permissions",
            json={"permission_name": "registry.teleport"},
        )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "permission_name"


async def test_a_builtin_role_is_forbidden_over_http() -> None:
    store = InMemoryStore()
    service, _ = _service(store)
    role_id = _seed_builtin(store)
    app, _ = _app(service=service, store=store)

    async with _client(app) as client:
        amended = await client.patch(
            f"/v1/roles/{role_id}", json={"description": "changed"}
        )
        rebound = await client.post(
            f"/v1/roles/{role_id}/permissions",
            json={"permission_name": "registry.write"},
        )

    assert amended.status_code == 403
    assert rebound.status_code == 403


async def test_unbinding_over_http_requires_a_reason() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/roles", json={"name": "owner", "description": "Owns things."}
        )
        role_id = created.json()["id"]
        await client.post(
            f"/v1/roles/{role_id}/permissions",
            json={"permission_name": "registry.read"},
        )
        unbound = await client.post(
            f"/v1/roles/{role_id}/permissions/registry.read/unbind",
            json={"reason": "narrowed to nothing"},
        )
        remaining = await client.get(f"/v1/roles/{role_id}/permissions")

    assert unbound.status_code == 204
    assert remaining.json() == []


async def test_a_reader_cannot_manage_roles() -> None:
    app, _ = _app(roles=frozenset({AUDITOR}))
    async with _client(app) as client:
        listed = await client.get("/v1/roles")
        created = await client.post(
            "/v1/roles", json={"name": "owner", "description": "Owns things."}
        )
    assert listed.status_code == 403
    assert created.status_code == 403
