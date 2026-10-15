"""Permission-change records are permanent (SC-005, V11).

The value of an audit trail is that what it says cannot be edited afterwards. So
this suite asserts absence: no route, and no member of the audit port, offers a
way to change or remove a record. An absence is easy to reintroduce by accident,
which is why it is asserted rather than assumed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx
from _inmemory import InMemoryAudit, InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.audit.queries import AuditQueryService
from gov.api.application.permission.audit import (
    PERMISSION_BOUND,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.ports import AuditPort
from gov.api.domain.identity.permissions import AUDITOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
AUDIT_PREFIX = "/v1/audit-events"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _app(store: InMemoryStore) -> FastAPI:
    app = create_app(
        audit_service=AuditQueryService(lambda: InMemoryUnitOfWork(store))
    )
    principal = Principal(
        subject="user-auditor",
        user_id="user-auditor",
        organisation_id=ORG,
        roles=frozenset({AUDITOR}),
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


def _record(store: InMemoryStore, permission: str) -> None:
    PermissionChangeRecorder(
        audit=InMemoryAudit(store), events=None, clock=lambda: NOW
    ).record(
        PermissionChange(
            organisation_id=ORG,
            actor="user-admin",
            action=PERMISSION_BOUND,
            target_type="role",
            target_id="role-1",
            reason=None,
            detail={"permission_name": permission},
        )
    )


def test_the_audit_surface_declares_no_mutating_route() -> None:
    app = _app(InMemoryStore())
    mutating = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith(AUDIT_PREFIX) and method in MUTATING
    }

    assert mutating == set(), f"the audit surface gained a write route: {mutating}"


def test_the_audit_port_offers_no_way_to_change_history() -> None:
    members = {
        name
        for name, value in vars(AuditPort).items()
        if not name.startswith("_") and callable(value)
    }

    assert members == {"record", "history_for", "search"}, (
        "the audit port grew a member that could amend or remove a record: "
        f"{members}"
    )


async def test_a_write_attempt_on_the_audit_surface_is_not_routed() -> None:
    store = InMemoryStore()
    app = _app(store)
    before = deepcopy(store.audit)

    async with _client(app) as client:
        for method in ("post", "put", "patch", "delete"):
            response = await getattr(client, method)(f"{AUDIT_PREFIX}/role/role-1")
            assert response.status_code in (404, 405), f"{method} was routed"
        # A write to the collection itself is equally refused.
        response = await client.post(AUDIT_PREFIX, json={"action": "forged"})

    assert response.status_code in (404, 405)
    assert store.audit == before, "the trail changed under a refused write"


async def test_the_records_a_reader_sees_are_unchanged_by_a_refused_write() -> None:
    store = InMemoryStore()
    _record(store, "registry.read")
    _record(store, "registry.write")
    app = _app(store)
    before = deepcopy(store.audit)

    async with _client(app) as client:
        await client.delete(f"{AUDIT_PREFIX}/role/role-1")
        listing = await client.get(AUDIT_PREFIX, params={"target_id": "role-1"})

    assert len(listing.json()) == 2
    assert store.audit == before
