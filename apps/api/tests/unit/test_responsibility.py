"""Tests for responsibility-based control (T043, T044, US4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.permission.responsibility import ResponsibilityService
from gov.api.application.ports import (
    AgentRecord,
    NotFoundError,
    UserRecord,
    ValidationFailure,
)
from gov.api.domain.identity.permissions import AUDITOR, PLATFORM_ADMINISTRATOR
from gov.api.domain.permission.responsibility import is_accountable, validate_transfer
from gov.api.domain.permission.rules import PermissionRuleError
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
DANA = "user-dana"
ERIK = "user-erik"
AGENT = "agent-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


# ------------------------------------------------------------ domain rules


def test_a_transfer_requires_an_incoming_holder() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_transfer(
            current_owner_user_id=DANA, new_owner_user_id="  ", reason="handover"
        )
    assert excinfo.value.code == "owner_required"


def test_a_transfer_requires_a_reason() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_transfer(
            current_owner_user_id=DANA, new_owner_user_id=ERIK, reason=""
        )
    assert excinfo.value.code == "reason_required"


def test_a_transfer_to_the_same_person_changes_nothing() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_transfer(
            current_owner_user_id=DANA, new_owner_user_id=DANA, reason="handover"
        )
    assert excinfo.value.code == "no_change"


def test_a_valid_transfer_is_accepted() -> None:
    validate_transfer(
        current_owner_user_id=DANA, new_owner_user_id=ERIK, reason="moved teams"
    )


def test_accountability_is_a_comparison_not_a_lookup() -> None:
    assert is_accountable(owner_user_id=DANA, user_id=DANA) is True
    assert is_accountable(owner_user_id=DANA, user_id=ERIK) is False
    assert is_accountable(owner_user_id=None, user_id=DANA) is False


# --------------------------------------------------------------- use cases


def _store() -> InMemoryStore:
    store = InMemoryStore()
    for user_id, name in ((DANA, "Dana"), (ERIK, "Erik"), (ACTOR, "Ada")):
        store.users[user_id] = UserRecord(
            id=user_id,
            organisation_id=ORG,
            external_subject=f"sub-{user_id}",
            display_name=name,
            email=f"{user_id}@example.invalid",
        )
    store.agents[AGENT] = AgentRecord(
        id=AGENT,
        organisation_id=ORG,
        name="ap-reconciler",
        owner_user_id=DANA,
        created_at=NOW,
        updated_at=NOW,
    )
    return store


def _service(
    store: InMemoryStore | None = None, cache: EffectivePermissionCache | None = None
) -> tuple[ResponsibilityService, InMemoryStore]:
    store = store if store is not None else _store()
    return (
        ResponsibilityService(
            lambda: InMemoryUnitOfWork(store), clock=lambda: NOW, cache=cache
        ),
        store,
    )


def test_the_current_holder_is_returned() -> None:
    service, _ = _service()
    view = service.get(organisation_id=ORG, agent_id=AGENT)
    assert view.accountable_user_id == DANA


def test_a_transfer_moves_accountability_and_records_why() -> None:
    service, store = _service()
    view = service.transfer(
        organisation_id=ORG,
        agent_id=AGENT,
        accountable_user_id=ERIK,
        reason="Dana moved to another team",
        actor=ACTOR,
    )

    assert view.accountable_user_id == ERIK
    assert store.agents[AGENT].owner_user_id == ERIK
    assert store.audit[-1].action == "responsibility.transfer"
    assert store.audit[-1].reason == "Dana moved to another team"


def test_the_history_is_derived_from_the_audit_trail() -> None:
    """Not from a second table: the trail is the only history there is."""
    service, store = _service()
    service.transfer(
        organisation_id=ORG,
        agent_id=AGENT,
        accountable_user_id=ERIK,
        reason="moved teams",
        actor=ACTOR,
    )
    view = service.get(organisation_id=ORG, agent_id=AGENT)

    assert [entry.action for entry in view.history] == ["responsibility.transfer"]
    assert view.history[0].accountable_user_id == ERIK
    # Nothing was written to a responsibility table, because there is not one.
    assert not hasattr(store, "responsibilities")


def test_a_transfer_without_a_reason_is_refused() -> None:
    service, store = _service()
    with pytest.raises(ValidationFailure) as excinfo:
        service.transfer(
            organisation_id=ORG,
            agent_id=AGENT,
            accountable_user_id=ERIK,
            reason="   ",
            actor=ACTOR,
        )
    assert excinfo.value.errors[0]["field"] == "reason"
    assert store.agents[AGENT].owner_user_id == DANA


def test_transferring_to_the_same_person_is_refused() -> None:
    service, _ = _service()
    with pytest.raises(ValidationFailure):
        service.transfer(
            organisation_id=ORG,
            agent_id=AGENT,
            accountable_user_id=DANA,
            reason="no change",
            actor=ACTOR,
        )


def test_accountability_cannot_rest_with_a_disabled_user() -> None:
    store = _store()
    store.users[ERIK].status = "disabled"
    service, _ = _service(store)

    with pytest.raises(ValidationFailure) as excinfo:
        service.transfer(
            organisation_id=ORG,
            agent_id=AGENT,
            accountable_user_id=ERIK,
            reason="moved teams",
            actor=ACTOR,
        )
    assert excinfo.value.errors[0]["field"] == "accountable_user_id"


def test_transferring_an_unknown_agent_or_user_is_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        service.transfer(
            organisation_id=ORG,
            agent_id="missing",
            accountable_user_id=ERIK,
            reason="moved teams",
            actor=ACTOR,
        )
    with pytest.raises(NotFoundError):
        service.transfer(
            organisation_id=ORG,
            agent_id=AGENT,
            accountable_user_id="missing",
            reason="moved teams",
            actor=ACTOR,
        )


def test_a_transfer_invalidates_the_decision_cache() -> None:
    """Authority follows accountability, so the cache must move with it."""
    cache = EffectivePermissionCache()
    service, _ = _service(cache=cache)
    before = cache.generation(ORG)
    service.transfer(
        organisation_id=ORG,
        agent_id=AGENT,
        accountable_user_id=ERIK,
        reason="moved teams",
        actor=ACTOR,
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
    app = create_app(responsibility_service=service)
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


async def test_responsibility_can_be_read_and_transferred_over_http() -> None:
    app, _ = _app()
    async with _client(app) as client:
        before = await client.get(f"/v1/agents/{AGENT}/responsibility")
        transferred = await client.post(
            f"/v1/agents/{AGENT}/responsibility",
            json={"accountable_user_id": ERIK, "reason": "Dana moved teams"},
        )
        after = await client.get(f"/v1/agents/{AGENT}/responsibility")

    assert before.json()["accountable_user_id"] == DANA
    assert transferred.status_code == 200
    assert after.json()["accountable_user_id"] == ERIK
    assert after.json()["history"][0]["reason"] == "Dana moved teams"


async def test_a_transfer_without_a_reason_is_rejected_over_http() -> None:
    app, _ = _app()
    async with _client(app) as client:
        response = await client.post(
            f"/v1/agents/{AGENT}/responsibility",
            json={"accountable_user_id": ERIK, "reason": ""},
        )
    assert response.status_code == 422


async def test_an_unknown_agent_is_not_found_over_http() -> None:
    app, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/agents/missing/responsibility")
    assert response.status_code == 404


async def test_a_reader_cannot_read_or_move_responsibility() -> None:
    app, _ = _app(roles=frozenset({AUDITOR}))
    async with _client(app) as client:
        read = await client.get(f"/v1/agents/{AGENT}/responsibility")
        moved = await client.post(
            f"/v1/agents/{AGENT}/responsibility",
            json={"accountable_user_id": ERIK, "reason": "moved"},
        )
    assert read.status_code == 403
    assert moved.status_code == 403
