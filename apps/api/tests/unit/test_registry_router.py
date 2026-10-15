"""HTTP tests for the Agent Registry endpoints (T042, T043, US1)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import httpx
from _inmemory import (
    InMemoryAuthorizationEngine,
    InMemoryStore,
    InMemoryUnitOfWork,
    assign_builtin_role,
    seed_builtin_roles,
)
from fastapi import FastAPI

from gov.api.application.permission.effective import EffectivePermissionResolver
from gov.api.application.ports import UserRecord
from gov.api.application.registry.service import RegistryService
from gov.api.domain.identity.permissions import (
    AGENT_DEVELOPER,
    AUDITOR,
    PLATFORM_ADMINISTRATOR,
)
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _app(
    *,
    roles: frozenset[str] = frozenset({PLATFORM_ADMINISTRATOR}),
    organisation_id: str = ORG,
    authenticate: bool = True,
    configure_service: bool = True,
) -> tuple[FastAPI, RegistryService, InMemoryStore]:
    store = InMemoryStore()
    counter = itertools.count(1)
    service = RegistryService(
        lambda: InMemoryUnitOfWork(store),
        clock=lambda: NOW,
        new_id=lambda: f"id-{next(counter)}",
    )
    # Authorization on these routes now comes from effective permissions, so the
    # fixture gives the caller a real role assignment rather than a role list.
    seed_builtin_roles(store)
    _ensure_user(store, ACTOR, organisation_id)
    _set_role(store, ACTOR, organisation_id, roles)

    app = create_app(registry_service=service if configure_service else None)
    app.state.permission_resolver = EffectivePermissionResolver(
        lambda: InMemoryUnitOfWork(store), clock=lambda: NOW
    )
    app.state.authorization_engine = InMemoryAuthorizationEngine()
    app.state.test_store = store

    if authenticate:
        _as(app, roles, organisation_id=organisation_id)

        # The principal is installed the way the authentication middleware will
        # install it, so the shared permission guard is exercised for real.
        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = request.app.state.test_principal
            return await call_next(request)

    return app, service, store


def _as(
    app: FastAPI,
    roles: frozenset[str],
    *,
    user_id: str = ACTOR,
    organisation_id: str = ORG,
) -> None:
    """Change who the next request is authenticated as."""
    store: InMemoryStore = app.state.test_store
    _ensure_user(store, user_id, organisation_id)
    _set_role(store, user_id, organisation_id, roles)
    # Changing an assignment invalidates the resolved set, exactly as the
    # application does when it revokes or grants one (FR-020).
    app.state.permission_resolver.invalidate(organisation_id)

    app.state.test_principal = Principal(
        subject=user_id,
        user_id=user_id,
        organisation_id=organisation_id,
        roles=roles,
    )


def _ensure_user(store: InMemoryStore, user_id: str, organisation_id: str) -> None:
    if user_id not in store.users:
        store.users[user_id] = UserRecord(
            id=user_id,
            organisation_id=organisation_id,
            external_subject=f"sub-{user_id}",
            display_name=user_id,
            email=f"{user_id}@example.invalid",
        )


def _set_role(
    store: InMemoryStore,
    user_id: str,
    organisation_id: str,
    roles: frozenset[str],
) -> None:
    """Give this user exactly the built-in role under test, and nothing else."""
    for existing in [key for key in store.assignments if key.startswith("builtin-")]:
        del store.assignments[existing]
    assign_builtin_role(
        store,
        organisation_id=organisation_id,
        user_id=user_id,
        code=next(iter(roles)),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def test_a_new_organisation_has_no_agents() -> None:
    app, _, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/agents")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "next_page_token": None}


async def test_registering_an_agent_returns_the_created_resource() -> None:
    app, _, store = _app()
    async with _client(app) as client:
        response = await client.post(
            "/v1/agents",
            json={
                "name": "ap-reconciler",
                "owner_user_id": "user-1",
                "description": "reconciles accounts payable",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "ap-reconciler"
    assert body["status"] == "draft"
    assert body["active_version_id"] is None
    assert datetime.fromisoformat(body["created_at"]) == NOW
    assert datetime.fromisoformat(body["updated_at"]) == NOW
    assert len(store.audit) == 1
    assert store.events[0].event_type == "agent.registered"


async def test_a_duplicate_name_is_a_conflict() -> None:
    app, _, _ = _app()
    payload = {"name": "ap-reconciler", "owner_user_id": "user-1"}
    async with _client(app) as client:
        first = await client.post("/v1/agents", json=payload)
        second = await client.post("/v1/agents", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_a_registration_without_an_owner_names_the_field() -> None:
    """US1 scenario 4: the response identifies what is missing."""
    app, _, store = _app()
    async with _client(app) as client:
        response = await client.post(
            "/v1/agents", json={"name": "ap-reconciler", "owner_user_id": ""}
        )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert {item["field"] for item in body["errors"]} == {"owner_user_id"}
    assert store.agents == {}


async def test_a_reader_cannot_register_an_agent() -> None:
    app, _, _ = _app(roles=frozenset({AUDITOR}))
    async with _client(app) as client:
        response = await client.post(
            "/v1/agents", json={"name": "ap-reconciler", "owner_user_id": "user-1"}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_an_agent_can_be_retrieved_by_id() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        response = await client.get(f"/v1/agents/{created.id}")
    assert response.status_code == 200
    assert response.json()["id"] == created.id


async def test_an_unknown_agent_is_not_found() -> None:
    app, _, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/agents/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_an_agent_can_be_updated() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        response = await client.patch(
            f"/v1/agents/{created.id}",
            json={"description": "reconciles accounts payable"},
        )
    assert response.status_code == 200
    assert response.json()["description"] == "reconciles accounts payable"


async def test_only_an_administrator_may_retire_an_agent() -> None:
    """Retiring is a distinct authority from writing."""
    app, service, _ = _app(roles=frozenset({AGENT_DEVELOPER}))
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        refused = await client.patch(
            f"/v1/agents/{created.id}", json={"status": "retired"}
        )
        _as(app, frozenset({PLATFORM_ADMINISTRATOR}))
        allowed = await client.patch(
            f"/v1/agents/{created.id}", json={"status": "retired"}
        )

    assert refused.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "retired"


async def test_a_lifecycle_state_may_not_be_assigned_directly() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        response = await client.patch(
            f"/v1/agents/{created.id}", json={"status": "active"}
        )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "status"


async def test_adding_a_version_and_listing_versions() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        added = await client.post(
            f"/v1/agents/{created.id}/versions",
            json={"version": "1.0.0", "owner_user_id": "user-1"},
        )
        listed = await client.get(f"/v1/agents/{created.id}/versions")

    assert added.status_code == 201
    assert added.json()["status"] == "draft"
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == ["1.0.0"]


async def test_a_malformed_version_names_the_field() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        response = await client.post(
            f"/v1/agents/{created.id}/versions",
            json={"version": "not-a-version", "owner_user_id": "user-1"},
        )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "version"


async def test_a_duplicate_version_is_a_conflict() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    body = {"version": "1.0.0", "owner_user_id": "user-1"}
    async with _client(app) as client:
        await client.post(f"/v1/agents/{created.id}/versions", json=body)
        duplicate = await client.post(f"/v1/agents/{created.id}/versions", json=body)
    assert duplicate.status_code == 409


async def test_versions_for_an_unknown_agent_are_not_found() -> None:
    app, _, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/agents/missing/versions")
    assert response.status_code == 404


async def test_releasing_a_version_demotes_the_previous_one() -> None:
    """FR-006 and US1 scenario 2."""
    app, service, store = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        await client.post(
            f"/v1/agents/{created.id}/versions",
            json={"version": "1.0.0", "owner_user_id": "user-1"},
        )
        await client.post(
            f"/v1/agents/{created.id}/versions",
            json={"version": "1.1.0", "owner_user_id": "user-1"},
        )
        first_release = await client.post(
            f"/v1/agents/{created.id}/versions/1.0.0/release"
        )
        second_release = await client.post(
            f"/v1/agents/{created.id}/versions/1.1.0/release"
        )
        versions = await client.get(f"/v1/agents/{created.id}/versions")
        agent = await client.get(f"/v1/agents/{created.id}")

    assert first_release.status_code == 200
    assert second_release.status_code == 200
    statuses = {item["version"]: item["status"] for item in versions.json()}
    assert statuses == {"1.0.0": "deprecated", "1.1.0": "released"}
    assert agent.json()["status"] == "active"
    assert agent.json()["active_version_id"] == second_release.json()["id"]
    assert store.versions[second_release.json()["id"]].released_at == NOW


async def test_releasing_an_unknown_version_is_not_found() -> None:
    app, service, _ = _app()
    created = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(app) as client:
        response = await client.post(
            f"/v1/agents/{created.id}/versions/9.9.9/release"
        )
    assert response.status_code == 404


async def test_agents_are_scoped_to_the_callers_organisation() -> None:
    other_org_app, service, _ = _app(organisation_id="org-2")
    service.create_agent(
        organisation_id="org-2", name="other-agent", owner_user_id=ACTOR, actor=ACTOR
    )
    async with _client(other_org_app) as client:
        visible = await client.get("/v1/agents")
    assert visible.json()["total"] == 1

    org_one_app, _, _ = _app()
    async with _client(org_one_app) as client:
        hidden = await client.get("/v1/agents")
    assert hidden.json()["total"] == 0


async def test_listing_is_paginated_with_an_opaque_token() -> None:
    app, service, _ = _app()
    for index in range(3):
        service.create_agent(
            organisation_id=ORG,
            name=f"agent-{index}",
            owner_user_id=ACTOR,
            actor=ACTOR,
        )
    async with _client(app) as client:
        first = await client.get("/v1/agents", params={"page_size": 2})
        token = first.json()["next_page_token"]
        second = await client.get(
            "/v1/agents", params={"page_size": 2, "page_token": token}
        )

    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert token is not None
    assert len(second.json()["items"]) == 1
    assert second.json()["next_page_token"] is None


async def test_a_malformed_page_token_is_rejected() -> None:
    app, _, _ = _app()
    async with _client(app) as client:
        response = await client.get("/v1/agents", params={"page_token": "!!!"})
    assert response.status_code == 422


async def test_an_unauthenticated_caller_is_refused() -> None:
    app, _, _ = _app(authenticate=False)
    async with _client(app) as client:
        response = await client.get("/v1/agents")
    assert response.status_code == 401


async def test_the_surface_fails_closed_without_a_service() -> None:
    app, _, _ = _app(configure_service=False)
    async with _client(app) as client:
        response = await client.get("/v1/agents")
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


# ------------------------------------------------- accountability for writes


async def test_a_developer_may_write_the_agent_they_are_accountable_for() -> None:
    app, service, _ = _app(roles=frozenset({AGENT_DEVELOPER}))
    mine = service.create_agent(
        organisation_id=ORG, name="mine", owner_user_id=ACTOR, actor=ACTOR
    )

    async with _client(app) as client:
        response = await client.patch(
            f"/v1/agents/{mine.id}", json={"description": "updated"}
        )
    assert response.status_code == 200


async def test_a_developer_cannot_write_another_persons_agent() -> None:
    """FR-014, and the reason the rule lives in the policy rather than the route."""
    app, service, _ = _app(roles=frozenset({AGENT_DEVELOPER}))
    theirs = service.create_agent(
        organisation_id=ORG, name="theirs", owner_user_id="user-1", actor=ACTOR
    )

    async with _client(app) as client:
        response = await client.patch(
            f"/v1/agents/{theirs.id}", json={"description": "updated"}
        )

    assert response.status_code == 403
    assert response.json()["errors"][0]["message"] == "abac.resource_accountability"


async def test_an_administrator_may_write_any_agent() -> None:
    """The exemption is a permission, so it is granted rather than hard-coded."""
    app, service, _ = _app()
    theirs = service.create_agent(
        organisation_id=ORG, name="theirs", owner_user_id="user-1", actor=ACTOR
    )

    async with _client(app) as client:
        response = await client.patch(
            f"/v1/agents/{theirs.id}", json={"description": "updated"}
        )
    assert response.status_code == 200


async def test_a_developer_cannot_release_another_persons_version() -> None:
    app, service, _ = _app(roles=frozenset({AGENT_DEVELOPER}))
    theirs = service.create_agent(
        organisation_id=ORG, name="theirs", owner_user_id="user-1", actor=ACTOR
    )
    service.add_version(
        organisation_id=ORG,
        agent_id=theirs.id,
        version="1.0.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )

    async with _client(app) as client:
        response = await client.post(
            f"/v1/agents/{theirs.id}/versions/1.0.0/release"
        )
    assert response.status_code == 403
