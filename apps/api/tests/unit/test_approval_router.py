"""HTTP tests for the Approval Center endpoints (T065, US3).

These assert the statuses the task calls for: 403 for self-approval, 409 for a
settled request, and a persisted decision otherwise.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.approval.service import ApprovalService
from gov.api.domain.identity.permissions import AUDITOR, BUSINESS_APPROVER
from gov.api.interface.approval.router import get_clock
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
REQUESTER = "user-requester"
APPROVER = "user-approver"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
WINDOW = NOW + timedelta(hours=12)
DECIDED_AT = NOW + timedelta(minutes=30)


def _service(store: InMemoryStore) -> ApprovalService:
    counter = itertools.count(1)
    return ApprovalService(
        lambda: InMemoryUnitOfWork(store),
        new_id=lambda: f"approval-{next(counter)}",
    )


def _app(
    *,
    roles: frozenset[str] = frozenset({BUSINESS_APPROVER}),
    user_id: str = APPROVER,
    authenticate: bool = True,
    configure_service: bool = True,
) -> tuple[FastAPI, ApprovalService, InMemoryStore]:
    store = InMemoryStore()
    service = _service(store)
    app = create_app(approval_service=service if configure_service else None)
    app.dependency_overrides[get_clock] = lambda: (lambda: DECIDED_AT)

    if authenticate:
        principal = Principal(
            subject=user_id,
            user_id=user_id,
            organisation_id=ORG,
            roles=roles,
        )

        # The principal is installed the way the authentication middleware will
        # install it, so the shared permission guard is exercised for real rather
        # than bypassed by a dependency override.
        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = principal
            return await call_next(request)

    return app, service, store


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


def _raise(service: ApprovalService, **overrides: object) -> Any:
    payload: dict[str, object] = {
        "organisation_id": ORG,
        "invocation_id": "inv-1",
        "requested_by": REQUESTER,
        "expires_at": WINDOW,
        "actor": REQUESTER,
    }
    payload.update(overrides)
    return service.raise_request(**payload)  # type: ignore[arg-type]


async def test_the_pending_queue_lists_requests_with_their_evidence() -> None:
    app, service, _ = _app()
    request = _raise(service, evidence={"risk_level": "high"})

    async with _client(app) as client:
        response = await client.get("/v1/approval-requests")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == request.id
    assert body["items"][0]["status"] == "pending"
    assert body["items"][0]["evidence"] == {"risk_level": "high"}


async def test_a_single_request_can_be_retrieved() -> None:
    app, service, _ = _app()
    request = _raise(service)

    async with _client(app) as client:
        response = await client.get(f"/v1/approval-requests/{request.id}")

    assert response.status_code == 200
    assert response.json()["id"] == request.id


async def test_an_unknown_request_is_a_problem_response() -> None:
    app, _, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/approval-requests/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


async def test_an_approver_can_decide_a_request() -> None:
    app, service, store = _app()
    request = _raise(service)

    async with _client(app) as client:
        response = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "approve", "reason": "checked against the invoice"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    # The approver is the authenticated principal, not anything the caller sent.
    assert body["decisions"][0]["approver_user_id"] == APPROVER
    assert store.approvals[request.id].status.value == "approved"
    assert len(store.audit) == 2


async def test_a_caller_without_the_approval_permission_is_forbidden() -> None:
    app, service, _ = _app(roles=frozenset({AUDITOR}))
    request = _raise(service)

    async with _client(app) as client:
        response = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "approve", "reason": "looks fine"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_the_requester_cannot_approve_their_own_request() -> None:
    """FR-022: self-approval is refused with 403, not accepted."""
    app, service, store = _app(user_id=REQUESTER)
    request = _raise(service)

    async with _client(app) as client:
        response = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "approve", "reason": "self approved"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert store.approvals[request.id].status.value == "pending"


async def test_deciding_a_settled_request_is_a_conflict() -> None:
    app, service, _ = _app()
    request = _raise(service)
    async with _client(app) as client:
        first = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "approve", "reason": "approved"},
        )
        second = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "reject", "reason": "changed my mind"},
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_a_decision_without_a_reason_is_rejected() -> None:
    app, service, _ = _app()
    request = _raise(service)

    async with _client(app) as client:
        response = await client.post(
            f"/v1/approval-requests/{request.id}/decisions",
            json={"decision": "approve", "reason": ""},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_an_unauthenticated_caller_cannot_list_requests() -> None:
    app, _, _ = _app(authenticate=False)
    async with _client(app) as client:
        response = await client.get("/v1/approval-requests")
    assert response.status_code == 401


async def test_endpoints_fail_closed_when_the_service_is_not_configured() -> None:
    app, _, _ = _app(configure_service=False)
    async with _client(app) as client:
        response = await client.get("/v1/approval-requests")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


@pytest.mark.parametrize("state", ["approved", "rejected"])
async def test_requests_can_be_filtered_by_state(state: str) -> None:
    app, service, _ = _app()
    request = _raise(service)
    service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision=state.rstrip("ed") if state == "rejected" else "approve",
        reason="decided",
        at=DECIDED_AT,
    )

    async with _client(app) as client:
        response = await client.get(
            "/v1/approval-requests", params={"status": state}
        )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == state
