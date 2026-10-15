"""Tests for the audit query and replay surface (T049, T050, US5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from _inmemory import InMemoryAudit, InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.audit.queries import AuditFilter, AuditQueryService
from gov.api.application.permission.audit import (
    PERMISSION_BOUND,
    PERMISSION_UNBOUND,
    ROLE_CREATED,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.domain.identity.permissions import AUDITOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
OTHER_ORG = "org-2"
ACTOR = "user-admin"
ROLE = "role-1"
START = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


class _Clock:
    """A clock the test advances, so events have a real order."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def tick(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


def _record(
    store: InMemoryStore,
    clock: _Clock,
    *,
    action: str,
    permission: str | None = None,
    reason: str | None = None,
    actor: str = ACTOR,
    organisation_id: str = ORG,
) -> None:
    detail = {"permission_name": permission} if permission else {}
    PermissionChangeRecorder(
        audit=InMemoryAudit(store), events=None, clock=clock
    ).record(
        PermissionChange(
            organisation_id=organisation_id,
            actor=actor,
            action=action,
            target_type="role",
            target_id=ROLE,
            reason=reason,
            detail=detail,
        )
    )


def _service(store: InMemoryStore) -> AuditQueryService:
    return AuditQueryService(lambda: InMemoryUnitOfWork(store))


# ---------------------------------------------------------------- searching


def test_a_search_returns_the_entries_that_match() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED)
    clock.tick(minutes=1)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")

    service = _service(store)
    everything = service.search(organisation_id=ORG, criteria=AuditFilter())
    bound = service.search(
        organisation_id=ORG, criteria=AuditFilter(target_type="role")
    )
    unbind = service.search(
        organisation_id=ORG, criteria=AuditFilter(actor="nobody")
    )

    assert len(everything) == 2
    assert len(bound) == 2
    assert unbind == []


def test_a_search_can_be_narrowed_by_time() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED)
    clock.tick(hours=1)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")

    service = _service(store)
    later_only = service.search(
        organisation_id=ORG,
        criteria=AuditFilter(since=START + timedelta(minutes=30)),
    )

    assert len(later_only) == 1
    assert later_only[0].action == PERMISSION_BOUND


def test_a_search_never_crosses_organisations() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED, organisation_id=OTHER_ORG)
    _record(store, clock, action=ROLE_CREATED)

    service = _service(store)
    assert len(service.search(organisation_id=ORG, criteria=AuditFilter())) == 1
    assert len(service.search(organisation_id=OTHER_ORG, criteria=AuditFilter())) == 1


# -------------------------------------------------------------- reconstruct


def test_reconstruction_returns_the_chain_oldest_first() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED)
    clock.tick(minutes=5)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")

    service = _service(store)
    chain = service.reconstruct(
        organisation_id=ORG, target_type="role", target_id=ROLE
    )
    assert [entry.action for entry in chain] == [ROLE_CREATED, PERMISSION_BOUND]


def test_permissions_at_a_past_moment_come_from_the_record() -> None:
    """SC-004: the answer is replayed, not read from current state."""
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")
    granted_at = clock.now
    clock.tick(hours=1)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.write")
    clock.tick(hours=1)
    _record(
        store,
        clock,
        action=PERMISSION_UNBOUND,
        permission="registry.read",
        reason="narrowed to write-only",
    )

    service = _service(store)
    at_grant = service.permissions_at(
        organisation_id=ORG, role_id=ROLE, at=granted_at
    )
    after_unbind = service.permissions_at(
        organisation_id=ORG, role_id=ROLE, at=clock.now
    )

    assert at_grant.permissions == frozenset({"registry.read"})
    assert after_unbind.permissions == frozenset({"registry.write"})


def test_the_replayed_state_carries_its_evidence() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")

    service = _service(store)
    state = service.permissions_at(organisation_id=ORG, role_id=ROLE, at=clock.now)

    assert [entry.actor for entry in state.sources] == [ACTOR]
    assert state.sources[0].action == PERMISSION_BOUND


def test_a_moment_before_any_change_grants_nothing() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")

    service = _service(store)
    state = service.permissions_at(
        organisation_id=ORG, role_id=ROLE, at=START - timedelta(days=1)
    )
    assert state.permissions == frozenset()


# ------------------------------------------------------------------ routes


def _app(
    *,
    roles: frozenset[str] = frozenset({AUDITOR}),
    store: InMemoryStore | None = None,
    wire: bool = True,
) -> tuple[FastAPI, InMemoryStore]:
    store = store if store is not None else InMemoryStore()
    app = create_app(audit_service=_service(store) if wire else None)
    principal = Principal(
        subject="user-auditor",
        user_id="user-auditor",
        organisation_id=ORG,
        roles=roles,
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


async def test_an_auditor_can_search_the_trail() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED)
    _record(store, clock, action=PERMISSION_BOUND, permission="registry.read")
    app, _ = _app(store=store)

    async with _client(app) as client:
        everything = await client.get("/v1/audit-events")
        narrowed = await client.get(
            "/v1/audit-events", params={"target_type": "role"}
        )

    assert everything.status_code == 200
    assert len(everything.json()) == 2
    assert len(narrowed.json()) == 2


async def test_an_auditor_can_reconstruct_one_target() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    _record(store, clock, action=ROLE_CREATED)
    app, _ = _app(store=store)

    async with _client(app) as client:
        response = await client.get(f"/v1/audit-events/role/{ROLE}")

    assert response.status_code == 200
    assert [item["action"] for item in response.json()] == [ROLE_CREATED]


async def test_an_auditor_cannot_write_anything_here() -> None:
    """FR-024: read-only is the whole of the auditor's authority."""
    app, _ = _app()
    async with _client(app) as client:
        for method in ("post", "put", "patch", "delete"):
            response = await getattr(client, method)("/v1/audit-events")
            assert response.status_code in (404, 405), f"{method} was routed"


async def test_a_caller_without_the_read_permission_is_refused() -> None:
    app, _ = _app(roles=frozenset({"agent_developer"}))
    async with _client(app) as client:
        response = await client.get("/v1/audit-events")
    assert response.status_code == 403


async def test_the_audit_surface_fails_closed_without_a_service() -> None:
    app, _ = _app(wire=False)
    async with _client(app) as client:
        response = await client.get("/v1/audit-events")
    assert response.status_code == 503
