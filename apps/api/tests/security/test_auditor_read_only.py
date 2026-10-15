"""The auditor can review everything and change nothing (SC-008, V7, V12).

Read-only is the whole of the auditor's authority: the built-in matrix gives the
role `registry.read`, `audit.read`, `audit.export` and `dashboard.read`, and not
one write permission. This suite attempts every write route in this feature and
in the Agent Registry as an auditor, asserts each is refused, and asserts each
refusal is recorded - a refusal nobody can see is not evidence of anything.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from _harness import (
    ACTOR,
    ORG,
    permission_app,
    registry_app,
)
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from _surface import OWNED_PREFIXES, SURFACE, WRITE_METHODS, resolve
from fastapi import FastAPI

from gov.api.application.audit.denials import ACCESS_DENIED, DENIED_OUTCOME, DenialRecorder
from gov.api.domain.identity.permissions import AUDITOR

AUDITOR_ROLES = frozenset({AUDITOR})


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _recorder(store: InMemoryStore) -> DenialRecorder:
    return DenialRecorder(lambda: InMemoryUnitOfWork(store))


#: The Permission Center write routes: every table entry whose method writes.
PERMISSION_WRITES: tuple[tuple[str, str, dict[str, Any] | None], ...] = tuple(
    (method, path, body)
    for method, path, body, _required in SURFACE
    if method in WRITE_METHODS
)

#: The registry write routes, keyed by the route template the application
#: declares, so the coverage check compares like with like.
REGISTRY_WRITES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("POST", "/v1/agents", {"name": "ap-reconciler", "owner_user_id": ACTOR}),
    ("PATCH", "/v1/agents/{agent_id}", {"description": "updated"}),
    (
        "POST",
        "/v1/agents/{agent_id}/versions",
        {"version": "1.0.0", "owner_user_id": ACTOR},
    ),
    ("POST", "/v1/agents/{agent_id}/versions/{version}/release", None),
)

#: Routes under "/v1/agents" that the Permission Center owns, so the registry
#: coverage check does not claim them.
PERMISSION_OWNED_PATHS: frozenset[str] = frozenset(path for _, path, _, _ in SURFACE)


def _resolve_registry(path: str) -> str:
    return path.replace("{agent_id}", "agent-1").replace("{version}", "1.0.0")


@pytest.mark.parametrize(("method", "path", "body"), PERMISSION_WRITES)
async def test_the_auditor_is_refused_on_every_permission_write(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    denials = InMemoryStore()
    app, app_store = permission_app(
        roles=AUDITOR_ROLES, denial_recorder=_recorder(denials)
    )
    target = f"{method} {resolve(path)}"

    async with _client(app) as client:
        response = await client.request(method, resolve(path), json=body)

    assert response.status_code == 403, f"the auditor was allowed on {method} {path}"
    assert _refusal_recorded(denials, target), f"the refusal on {target} was not recorded"
    assert app_store.roles == {}, "a refused write changed permission state"
    assert app_store.assignments == {}


@pytest.mark.parametrize(("method", "path", "body"), REGISTRY_WRITES)
async def test_the_auditor_is_refused_on_every_registry_write(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    denials = InMemoryStore()
    app, app_store = registry_app(
        role_code=AUDITOR, denial_recorder=_recorder(denials)
    )
    target = f"{method} {_resolve_registry(path)}"

    async with _client(app) as client:
        response = await client.request(method, _resolve_registry(path), json=body)

    assert response.status_code == 403, f"the auditor was allowed on {method} {path}"
    assert _refusal_recorded(denials, target), f"the refusal on {target} was not recorded"
    assert app_store.agents == {}, "a refused write changed registry state"


async def test_the_auditor_can_read_what_the_review_needs() -> None:
    denials = InMemoryStore()
    app, _ = permission_app(
        roles=AUDITOR_ROLES, denial_recorder=_recorder(denials), wire_audit=True
    )

    async with _client(app) as client:
        trail = await client.get("/v1/audit-events")

    assert trail.status_code == 200
    assert trail.json() == []


async def test_the_auditor_reads_the_registry_without_writing_to_it() -> None:
    app, _ = registry_app(
        role_code=AUDITOR, denial_recorder=_recorder(InMemoryStore())
    )

    async with _client(app) as client:
        response = await client.get("/v1/agents")

    assert response.status_code == 200


def test_the_permission_write_table_covers_every_declared_write_route() -> None:
    """A write route missing from the table is a test failure, not a gap."""
    app, _ = permission_app(
        roles=AUDITOR_ROLES, denial_recorder=_recorder(InMemoryStore())
    )
    declared = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method in WRITE_METHODS
        and any(route.path.startswith(prefix) for prefix in OWNED_PREFIXES)
    }
    covered = {(method, path) for method, path, _ in PERMISSION_WRITES}

    assert declared - covered == set(), (
        f"uncovered Permission Center write routes: {sorted(declared - covered)}"
    )


def test_the_registry_write_table_covers_every_declared_write_route() -> None:
    app, _ = registry_app(
        role_code=AUDITOR, denial_recorder=_recorder(InMemoryStore())
    )
    declared = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method in WRITE_METHODS
        and route.path.startswith("/v1/agents")
        and route.path not in PERMISSION_OWNED_PATHS
    }
    covered = {(method, path) for method, path, _ in REGISTRY_WRITES}

    assert declared - covered == set(), (
        f"uncovered registry write routes: {sorted(declared - covered)}"
    )


def _refusal_recorded(store: InMemoryStore, target: str) -> bool:
    return any(
        entry.action == ACCESS_DENIED
        and entry.outcome == DENIED_OUTCOME
        and entry.actor == ACTOR
        and entry.organisation_id == ORG
        and entry.target_id == target
        for entry in store.audit
    )
