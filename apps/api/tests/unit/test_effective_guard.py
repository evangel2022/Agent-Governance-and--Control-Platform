"""Unit tests for the effective-permission guard (T012)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from starlette.requests import Request

from gov.api.application.permission.effective import EffectivePermissionResolver
from gov.api.application.ports import (
    AuthorizationDecision,
    DecisionUnavailable,
    RoleAssignmentRecord,
    RolePermissionRecord,
    RoleRecord,
    UserRecord,
)
from gov.api.interface.errors import (
    ForbiddenProblem,
    ServiceUnavailableProblem,
    UnauthorizedProblem,
)
from gov.api.interface.security.authorize import require_effective_permission
from gov.api.interface.security.oidc import Principal

ORG = "org-1"
USER = "user-1"
ROLE = "role-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


class _Engine:
    """A decision component that answers what the test tells it to."""

    def __init__(
        self, decision: AuthorizationDecision | None = None, *, fail: bool = False
    ) -> None:
        self._decision = decision
        self._fail = fail
        self.seen: list[dict[str, Any]] = []

    async def decide(self, decision_input: Any) -> AuthorizationDecision:
        self.seen.append(dict(decision_input))
        if self._fail:
            raise DecisionUnavailable("policy engine unreachable")
        assert self._decision is not None
        return self._decision


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.users[USER] = UserRecord(
        id=USER,
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana Developer",
        email="dana@example.invalid",
    )
    store.roles[ROLE] = RoleRecord(
        id=ROLE,
        organisation_id=ORG,
        code=None,
        name="erp-invoice-owner",
        description="Owns ERP invoice Agents.",
    )
    store.bindings["b-1"] = RolePermissionRecord(
        id="b-1",
        organisation_id=ORG,
        role_id=ROLE,
        permission_name="registry.write",
        granted_by="admin-1",
        granted_at=NOW,
    )
    store.assignments["a-1"] = RoleAssignmentRecord(
        id="a-1",
        organisation_id=ORG,
        user_id=USER,
        role_id=ROLE,
        scope_type="organisation",
        granted_by="admin-1",
        granted_at=NOW,
    )
    return store


def _request(principal: Principal | None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "PATCH",
        "scheme": "http",
        "path": "/v1/agents/agent-9",
        "raw_path": b"/v1/agents/agent-9",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


def _principal() -> Principal:
    return Principal(
        subject=USER, user_id=USER, organisation_id=ORG, roles=frozenset({"agent_developer"})
    )


def _guard(engine: _Engine, store: InMemoryStore, **overrides: Any) -> Any:
    resolver = EffectivePermissionResolver(
        lambda: InMemoryUnitOfWork(store), clock=lambda: NOW
    )
    payload: dict[str, Any] = {
        "resolver": resolver,
        "engine": engine,
        "permission": "registry.write",
    }
    payload.update(overrides)
    return require_effective_permission(**payload)


async def test_an_allowed_decision_lets_the_request_through() -> None:
    engine = _Engine(AuthorizationDecision(allowed=True, reason="granted"))
    await _guard(engine, _store())(_request(_principal()))
    assert engine.seen  # the engine was asked, rather than the guard deciding


async def test_the_guard_sends_the_callers_effective_permissions() -> None:
    engine = _Engine(AuthorizationDecision(allowed=True, reason="granted"))
    await _guard(engine, _store())(_request(_principal()))

    document = engine.seen[0]
    assert document["permission"] == "registry.write"
    assert document["permissions"] == ["registry.write"]
    assert document["organisation_id"] == ORG
    assert document["user_id"] == USER


async def test_a_denial_is_forbidden_and_names_the_rule() -> None:
    engine = _Engine(
        AuthorizationDecision(
            allowed=False, reason="denied", sources=("abac.resource_accountability",)
        )
    )
    with pytest.raises(ForbiddenProblem) as excinfo:
        await _guard(engine, _store())(_request(_principal()))

    assert excinfo.value.code == "forbidden"
    assert excinfo.value.errors[0]["message"] == "abac.resource_accountability"


async def test_a_denial_without_sources_still_says_what_was_missing() -> None:
    engine = _Engine(AuthorizationDecision(allowed=False, reason="deny by default"))
    with pytest.raises(ForbiddenProblem) as excinfo:
        await _guard(engine, _store())(_request(_principal()))
    assert "registry.write" in excinfo.value.errors[0]["message"]


async def test_an_unavailable_decision_engine_fails_closed() -> None:
    """An outage must never be reported as a permission decision."""
    with pytest.raises(ServiceUnavailableProblem):
        await _guard(_Engine(fail=True), _store())(_request(_principal()))


async def test_an_unauthenticated_caller_is_refused_without_asking_the_engine() -> None:
    engine = _Engine(AuthorizationDecision(allowed=True, reason="granted"))
    with pytest.raises(UnauthorizedProblem):
        await _guard(engine, _store())(_request(None))
    assert engine.seen == []


async def test_a_caller_with_no_permissions_is_still_put_to_the_engine() -> None:
    """Deny-by-default belongs to the decision component, not to the guard."""
    store = _store()
    store.assignments.clear()
    engine = _Engine(AuthorizationDecision(allowed=False, reason="deny by default"))

    with pytest.raises(ForbiddenProblem):
        await _guard(engine, store)(_request(_principal()))
    assert engine.seen[0]["permissions"] == []


async def test_a_resource_resolver_contributes_its_facts() -> None:
    engine = _Engine(AuthorizationDecision(allowed=True, reason="granted"))
    guard = _guard(
        engine,
        _store(),
        resource=lambda request: {
            "type": "agent",
            "id": "agent-9",
            "owner_user_id": USER,
        },
        requires_resource_accountability=True,
    )
    await guard(_request(_principal()))

    document = engine.seen[0]
    assert document["requires_resource_accountability"] is True
    assert document["resource"]["owner_user_id"] == USER


async def test_the_request_is_described_in_the_decision_context() -> None:
    engine = _Engine(AuthorizationDecision(allowed=True, reason="granted"))
    await _guard(engine, _store())(_request(_principal()))

    assert engine.seen[0]["context"] == {"path": "/v1/agents/agent-9", "method": "PATCH"}
