"""Tests for scoped role assignments (T029, T032, US2)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.permission.assignments import AssignmentService
from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.ports import (
    ConflictError,
    NotFoundError,
    RolePermissionRecord,
    RoleRecord,
    UserRecord,
    ValidationFailure,
)
from gov.api.domain.identity.permissions import AUDITOR, PLATFORM_ADMINISTRATOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
DEVELOPER = "user-dev"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

MANAGER_ROLE = "role-manager"
OWNER_ROLE = "role-owner"


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.users[DEVELOPER] = UserRecord(
        id=DEVELOPER,
        organisation_id=ORG,
        external_subject="sub-dev",
        display_name="Dana Developer",
        email="dana@example.invalid",
    )
    store.users[ACTOR] = UserRecord(
        id=ACTOR,
        organisation_id=ORG,
        external_subject="sub-admin",
        display_name="Ada Administrator",
        email="ada@example.invalid",
    )
    # A role that can manage permissions, and one that cannot.
    store.roles[MANAGER_ROLE] = RoleRecord(
        id=MANAGER_ROLE,
        organisation_id=ORG,
        code=None,
        name="permission-manager",
        description="Administers permissions.",
    )
    store.bindings["b-manage"] = RolePermissionRecord(
        id="b-manage",
        organisation_id=ORG,
        role_id=MANAGER_ROLE,
        permission_name="identity.manage",
        granted_by=ACTOR,
        granted_at=NOW,
    )
    store.roles[OWNER_ROLE] = RoleRecord(
        id=OWNER_ROLE,
        organisation_id=ORG,
        code=None,
        name="erp-invoice-owner",
        description="Owns ERP invoice Agents.",
    )
    store.bindings["b-read"] = RolePermissionRecord(
        id="b-read",
        organisation_id=ORG,
        role_id=OWNER_ROLE,
        permission_name="registry.read",
        granted_by=ACTOR,
        granted_at=NOW,
    )
    return store


def _service(
    store: InMemoryStore | None = None, cache: EffectivePermissionCache | None = None
) -> tuple[AssignmentService, InMemoryStore]:
    store = store if store is not None else _store()
    counter = itertools.count(1)
    return (
        AssignmentService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"assignment-{next(counter)}",
            cache=cache,
        ),
        store,
    )


def _assign(service: AssignmentService, **overrides: object) -> Any:
    payload: dict[str, object] = {
        "organisation_id": ORG,
        "user_id": DEVELOPER,
        "role_id": OWNER_ROLE,
        "scope_type": "organisation",
        "reason": "owns these Agents",
        "actor": ACTOR,
    }
    payload.update(overrides)
    return service.assign(**payload)  # type: ignore[arg-type]


# --------------------------------------------------------------- use cases


def test_an_assignment_is_created_and_recorded() -> None:
    service, store = _service()
    record = _assign(service)

    assert store.assignments[record.id].role_id == OWNER_ROLE
    assert store.audit[-1].action == "assignment.assign"
    assert store.audit[-1].reason == "owns these Agents"


@pytest.mark.parametrize(
    ("scope_type", "scope_id"),
    [("organisation", "agent-1"), ("agent", None), ("galaxy", "x")],
)
def test_an_inconsistent_scope_is_refused(scope_type: str, scope_id: str | None) -> None:
    service, store = _service()
    with pytest.raises(ValidationFailure):
        _assign(service, scope_type=scope_type, scope_id=scope_id)
    assert store.assignments == {}


def test_a_reason_is_required_to_assign() -> None:
    service, _ = _service()
    with pytest.raises(ValidationFailure) as excinfo:
        _assign(service, reason="   ")
    assert excinfo.value.errors[0]["field"] == "reason"


def test_a_duplicate_assignment_is_refused() -> None:
    service, store = _service()
    _assign(service)
    with pytest.raises(ConflictError):
        _assign(service)
    assert len(store.assignments) == 1


def test_assigning_a_retired_role_is_refused() -> None:
    service, store = _service()
    store.roles[OWNER_ROLE].status = "retired"
    with pytest.raises(ConflictError) as excinfo:
        _assign(service)
    assert excinfo.value.errors[0]["field"] == "role_id"


@pytest.mark.parametrize(
    ("field", "value"),
    [("user_id", "missing"), ("role_id", "missing")],
)
def test_assigning_to_something_that_does_not_exist_is_not_found(
    field: str, value: str
) -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        _assign(service, **{field: value})


def test_an_agent_scoped_assignment_keeps_its_scope() -> None:
    service, store = _service()
    record = _assign(service, scope_type="agent", scope_id="agent-9")
    assert store.assignments[record.id].scope_id == "agent-9"


# ---------------------------------------------------------------- revocation


def test_revoking_records_the_reason_and_ends_the_grant() -> None:
    service, store = _service()
    record = _assign(service)

    revoked = service.revoke(
        organisation_id=ORG,
        assignment_id=record.id,
        actor=ACTOR,
        reason="the developer left the team",
    )

    assert revoked.revoked_at == NOW
    assert revoked.revocation_reason == "the developer left the team"
    assert store.audit[-1].action == "assignment.revoke"


def test_revoking_requires_a_reason() -> None:
    service, store = _service()
    record = _assign(service)
    with pytest.raises(ValidationFailure):
        service.revoke(
            organisation_id=ORG, assignment_id=record.id, actor=ACTOR, reason=""
        )
    assert store.assignments[record.id].revoked_at is None


def test_revoking_something_already_ended_is_a_conflict() -> None:
    service, _ = _service()
    record = _assign(service)
    service.revoke(
        organisation_id=ORG, assignment_id=record.id, actor=ACTOR, reason="not needed"
    )
    with pytest.raises(ConflictError):
        service.revoke(
            organisation_id=ORG,
            assignment_id=record.id,
            actor=ACTOR,
            reason="again",
        )


def test_revoking_an_expired_assignment_is_a_conflict() -> None:
    service, _ = _service()
    record = _assign(service, expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ConflictError):
        service.revoke(
            organisation_id=ORG, assignment_id=record.id, actor=ACTOR, reason="late"
        )


# ---------------------------------------------------------- last authority


def test_the_last_authority_to_manage_permissions_cannot_be_revoked() -> None:
    """FR-027: an organisation must not be able to lock itself out."""
    store = _store()
    service, _ = _service(store)
    only = _assign(service, user_id=ACTOR, role_id=MANAGER_ROLE)

    with pytest.raises(ConflictError) as excinfo:
        service.revoke(
            organisation_id=ORG,
            assignment_id=only.id,
            actor=ACTOR,
            reason="removing my own access",
        )
    assert "last authority" in str(excinfo.value)
    assert store.assignments[only.id].revoked_at is None


def test_the_last_authority_may_be_revoked_once_another_holder_exists() -> None:
    store = _store()
    service, _ = _service(store)
    mine = _assign(service, user_id=ACTOR, role_id=MANAGER_ROLE)
    _assign(service, user_id=DEVELOPER, role_id=MANAGER_ROLE)

    revoked = service.revoke(
        organisation_id=ORG, assignment_id=mine.id, actor=ACTOR, reason="handing over"
    )
    assert revoked.revoked_at == NOW


def test_revoking_a_non_managing_role_is_never_blocked() -> None:
    """Only the managing authority is guarded; other grants are ordinary."""
    store = _store()
    service, _ = _service(store)
    _assign(service, user_id=ACTOR, role_id=MANAGER_ROLE)
    ordinary = _assign(service, role_id=OWNER_ROLE)

    revoked = service.revoke(
        organisation_id=ORG,
        assignment_id=ordinary.id,
        actor=ACTOR,
        reason="no longer needed",
    )
    assert revoked.revoked_at == NOW


def test_a_revocation_bumps_the_decision_cache() -> None:
    """FR-020: the change is visible at the next verification."""
    cache = EffectivePermissionCache()
    service, _ = _service(cache=cache)
    record = _assign(service)
    before = cache.generation(ORG)
    service.revoke(
        organisation_id=ORG, assignment_id=record.id, actor=ACTOR, reason="ended"
    )
    assert cache.generation(ORG) > before


# ------------------------------------------------------------------ routes


def _app(
    *,
    roles: frozenset[str] = frozenset({PLATFORM_ADMINISTRATOR}),
    store: InMemoryStore | None = None,
) -> tuple[FastAPI, InMemoryStore]:
    store = store if store is not None else _store()
    service, _ = _service(store)
    app = create_app(assignment_service=service)
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


async def test_an_assignment_can_be_created_listed_and_revoked() -> None:
    app, _ = _app()
    body = {
        "user_id": DEVELOPER,
        "role_id": OWNER_ROLE,
        "scope_type": "organisation",
        "reason": "owns these Agents",
    }
    async with _client(app) as client:
        created = await client.post("/v1/role-assignments", json=body)
        assignment_id = created.json()["id"]
        listed = await client.get("/v1/role-assignments")
        revoked = await client.post(
            f"/v1/role-assignments/{assignment_id}/revoke",
            json={"reason": "the developer left the team"},
        )
        still_active = await client.get(
            "/v1/role-assignments", params={"include_ended": "true"}
        )

    assert created.status_code == 201
    assert listed.json()[0]["id"] == assignment_id
    assert revoked.status_code == 200
    assert revoked.json()["revocation_reason"] == "the developer left the team"
    # The ended assignment is hidden from the default listing but retained.
    assert still_active.json()[0]["revoked_at"] is not None


async def test_a_duplicate_assignment_is_a_conflict_over_http() -> None:
    app, _ = _app()
    body = {
        "user_id": DEVELOPER,
        "role_id": OWNER_ROLE,
        "scope_type": "organisation",
        "reason": "owns these Agents",
    }
    async with _client(app) as client:
        await client.post("/v1/role-assignments", json=body)
        duplicate = await client.post("/v1/role-assignments", json=body)
    assert duplicate.status_code == 409


async def test_revoking_over_http_requires_a_reason() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/role-assignments",
            json={
                "user_id": DEVELOPER,
                "role_id": OWNER_ROLE,
                "scope_type": "organisation",
                "reason": "owns these Agents",
            },
        )
        response = await client.post(
            f"/v1/role-assignments/{created.json()['id']}/revoke",
            json={"reason": ""},
        )
    assert response.status_code == 422


async def test_an_inconsistent_scope_is_rejected_before_anything_is_stored() -> None:
    app, store = _app()
    async with _client(app) as client:
        response = await client.post(
            "/v1/role-assignments",
            json={
                "user_id": DEVELOPER,
                "role_id": OWNER_ROLE,
                "scope_type": "organisation",
                "scope_id": "agent-9",
                "reason": "owns these Agents",
            },
        )
    assert response.status_code == 422
    assert store.assignments == {}


async def test_a_reader_cannot_manage_assignments() -> None:
    app, _ = _app(roles=frozenset({AUDITOR}))
    async with _client(app) as client:
        listed = await client.get("/v1/role-assignments")
        created = await client.post(
            "/v1/role-assignments",
            json={
                "user_id": DEVELOPER,
                "role_id": OWNER_ROLE,
                "scope_type": "organisation",
                "reason": "owns these Agents",
            },
        )
    assert listed.status_code == 403
    assert created.status_code == 403
