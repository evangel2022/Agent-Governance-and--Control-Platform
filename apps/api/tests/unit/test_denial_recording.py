"""Refusals are recorded (FR-024, SC-008)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.audit.denials import (
    ACCESS_DENIED,
    ACCESS_INDETERMINATE,
    DENIED_OUTCOME,
    DenialRecorder,
)
from gov.api.application.ports import UnitOfWork
from gov.api.domain.identity.permissions import AGENT_DEVELOPER, PLATFORM_ADMINISTRATOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _app(*, recorder: DenialRecorder | None, roles: frozenset[str] | None) -> FastAPI:
    app = create_app(denial_recorder=recorder)
    if roles is not None:
        principal = Principal(
            subject="user-1", user_id="user-1", organisation_id=ORG, roles=roles
        )

        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = principal
            return await call_next(request)

    return app


def _recorder(store: InMemoryStore) -> DenialRecorder:
    return DenialRecorder(lambda: InMemoryUnitOfWork(store), clock=lambda: NOW)


def test_the_recorder_writes_a_denied_entry() -> None:
    store = InMemoryStore()
    _recorder(store).record(
        organisation_id=ORG,
        actor="user-1",
        status=403,
        method="post",
        path="/v1/roles",
        reason="the caller lacks identity.manage",
    )

    assert len(store.audit) == 1
    entry = store.audit[0]
    assert entry.outcome == DENIED_OUTCOME
    assert entry.action == ACCESS_DENIED
    assert entry.actor == "user-1"
    assert entry.organisation_id == ORG
    assert entry.target_id == "POST /v1/roles"
    assert entry.reason == "the caller lacks identity.manage"
    assert entry.occurred_at == NOW


def test_an_indeterminate_decision_is_recorded_as_such() -> None:
    store = InMemoryStore()
    _recorder(store).record(
        organisation_id=ORG,
        actor="user-1",
        status=503,
        method="get",
        path="/v1/agents",
        reason="the authorization decision could not be obtained",
    )

    assert store.audit[0].action == ACCESS_INDETERMINATE
    assert store.audit[0].outcome == DENIED_OUTCOME


async def test_a_refused_request_is_recorded_when_the_handler_is_wired() -> None:
    store = InMemoryStore()
    app = _app(recorder=_recorder(store), roles=frozenset({AGENT_DEVELOPER}))

    async with _client(app) as client:
        response = await client.get("/v1/audit-events")

    assert response.status_code == 403
    assert len(store.audit) == 1
    assert store.audit[0].action == ACCESS_DENIED
    assert store.audit[0].target_id == "GET /v1/audit-events"


async def test_an_unwired_recorder_records_nothing() -> None:
    store = InMemoryStore()
    app = _app(recorder=None, roles=frozenset({AGENT_DEVELOPER}))

    async with _client(app) as client:
        response = await client.get("/v1/audit-events")

    assert response.status_code == 403
    assert store.audit == []


async def test_an_unauthenticated_request_is_refused_and_not_attributed() -> None:
    """A request with no tenant cannot be written to a tenant-scoped trail."""
    store = InMemoryStore()
    app = _app(recorder=_recorder(store), roles=None)

    async with _client(app) as client:
        response = await client.get("/v1/audit-events")

    assert response.status_code == 401
    assert store.audit == []


async def test_a_failing_recorder_does_not_turn_a_refusal_into_a_success() -> None:
    class _Broken:
        def __call__(self) -> UnitOfWork:
            raise RuntimeError("audit sink unreachable")

    broken = cast(Callable[[], UnitOfWork], _Broken())
    app = _app(recorder=DenialRecorder(broken), roles=frozenset({AGENT_DEVELOPER}))

    async with _client(app) as client:
        response = await client.get("/v1/audit-events")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_fail_closed_is_recorded_when_a_decision_cannot_be_made() -> None:
    store = InMemoryStore()
    app = _app(recorder=_recorder(store), roles=frozenset({PLATFORM_ADMINISTRATOR}))

    async with _client(app) as client:
        response = await client.get("/v1/audit-events")

    # The permission is held, but the audit service is not wired: a 503 that
    # fails closed is a refusal and is recorded with its reason.
    assert response.status_code == 503
    assert len(store.audit) == 1
    assert store.audit[0].action == ACCESS_INDETERMINATE
