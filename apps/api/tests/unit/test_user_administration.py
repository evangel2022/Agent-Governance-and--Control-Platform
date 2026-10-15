"""Tests for user administration, use case and HTTP (T014, T015)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork
from fastapi import FastAPI

from gov.api.application.permission.users import UserService
from gov.api.application.ports import ConflictError, NotFoundError, ValidationFailure
from gov.api.domain.identity.permissions import AUDITOR, PLATFORM_ADMINISTRATOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _service(
    store: InMemoryStore | None = None,
) -> tuple[UserService, InMemoryStore]:
    store = store if store is not None else InMemoryStore()
    counter = itertools.count(1)
    return (
        UserService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"user-{next(counter)}",
        ),
        store,
    )


def _app(
    *,
    roles: frozenset[str] = frozenset({PLATFORM_ADMINISTRATOR}),
    service: UserService | None = None,
) -> tuple[FastAPI, InMemoryStore]:
    store = InMemoryStore()
    resolved = service if service is not None else _service(store)[0]
    app = create_app(user_service=resolved)
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


# --------------------------------------------------------------- use cases


def test_creating_a_user_records_a_permission_change() -> None:
    service, store = _service()
    user = service.create_user(
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana Developer",
        email="dana@example.invalid",
        actor=ACTOR,
    )

    assert store.users[user.id].display_name == "Dana Developer"
    assert store.audit[-1].action == "user.create"
    assert store.audit[-1].target_id == user.id


def test_a_duplicate_external_subject_is_refused() -> None:
    service, store = _service()
    service.create_user(
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana",
        email="dana@example.invalid",
        actor=ACTOR,
    )
    with pytest.raises(ConflictError):
        service.create_user(
            organisation_id=ORG,
            external_subject="sub-1",
            display_name="Dana Again",
            email="dana2@example.invalid",
            actor=ACTOR,
        )
    assert len(store.users) == 1


def test_an_incomplete_user_creates_nothing() -> None:
    service, store = _service()
    with pytest.raises(ValidationFailure) as excinfo:
        service.create_user(
            organisation_id=ORG,
            external_subject="",
            display_name="Dana",
            email="dana@example.invalid",
            actor=ACTOR,
        )
    assert excinfo.value.errors[0]["field"] == "external_subject"
    assert store.users == {}
    assert store.audit == []


def test_a_malformed_email_is_refused() -> None:
    service, _ = _service()
    with pytest.raises(ValidationFailure) as excinfo:
        service.create_user(
            organisation_id=ORG,
            external_subject="sub-1",
            display_name="Dana",
            email="not-an-address",
            actor=ACTOR,
        )
    assert excinfo.value.errors[0]["field"] == "email"


def test_disabling_a_user_requires_a_reason() -> None:
    service, _ = _service()
    user = service.create_user(
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana",
        email="dana@example.invalid",
        actor=ACTOR,
    )
    with pytest.raises(ValidationFailure) as excinfo:
        service.set_status(
            organisation_id=ORG, user_id=user.id, actor=ACTOR, active=False
        )
    assert excinfo.value.errors[0]["field"] == "reason"


def test_disabling_then_re_enabling_a_user_is_recorded() -> None:
    service, store = _service()
    user = service.create_user(
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana",
        email="dana@example.invalid",
        actor=ACTOR,
    )
    service.set_status(
        organisation_id=ORG,
        user_id=user.id,
        actor=ACTOR,
        active=False,
        reason="left the team",
    )
    assert store.users[user.id].status == "disabled"
    assert store.audit[-1].action == "user.disable"
    assert store.audit[-1].reason == "left the team"

    service.set_status(
        organisation_id=ORG, user_id=user.id, actor=ACTOR, active=True
    )
    assert store.users[user.id].status == "active"
    assert store.audit[-1].action == "user.enable"


def test_an_unknown_user_is_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        service.get_user(organisation_id=ORG, user_id="missing")


# ------------------------------------------------------------------ routes


async def test_a_user_can_be_created_and_listed() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/users",
            json={
                "external_subject": "sub-1",
                "display_name": "Dana Developer",
                "email": "dana@example.invalid",
            },
        )
        listed = await client.get("/v1/users")

    assert created.status_code == 201
    assert created.json()["status"] == "active"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


async def test_a_duplicate_subject_is_a_conflict_naming_the_field() -> None:
    app, _ = _app()
    body = {
        "external_subject": "sub-1",
        "display_name": "Dana",
        "email": "dana@example.invalid",
    }
    async with _client(app) as client:
        await client.post("/v1/users", json=body)
        duplicate = await client.post("/v1/users", json=body)

    assert duplicate.status_code == 409
    assert duplicate.json()["errors"][0]["field"] == "external_subject"


async def test_a_missing_field_is_rejected_before_anything_is_stored() -> None:
    app, store = _app()
    async with _client(app) as client:
        response = await client.post(
            "/v1/users", json={"external_subject": "sub-1", "display_name": "Dana"}
        )
    assert response.status_code == 422
    assert store.users == {}


async def test_a_reader_cannot_administer_users() -> None:
    app, _ = _app(roles=frozenset({AUDITOR}))
    async with _client(app) as client:
        listed = await client.get("/v1/users")
        created = await client.post(
            "/v1/users",
            json={
                "external_subject": "sub-1",
                "display_name": "Dana",
                "email": "dana@example.invalid",
            },
        )
    assert listed.status_code == 403
    assert created.status_code == 403


async def test_disabling_through_the_api_requires_a_reason() -> None:
    app, _ = _app()
    async with _client(app) as client:
        created = await client.post(
            "/v1/users",
            json={
                "external_subject": "sub-1",
                "display_name": "Dana",
                "email": "dana@example.invalid",
            },
        )
        user_id = created.json()["id"]
        refused = await client.patch(f"/v1/users/{user_id}", json={"status": "disabled"})
        allowed = await client.patch(
            f"/v1/users/{user_id}",
            json={"status": "disabled", "reason": "left the team"},
        )

    assert refused.status_code == 422
    assert refused.json()["errors"][0]["field"] == "reason"
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "disabled"


async def test_the_surface_fails_closed_without_a_service() -> None:
    # Authenticated, but nothing wired: the guard passes and the missing service
    # is what the caller meets.
    app = create_app()
    principal = Principal(
        subject=ACTOR,
        user_id=ACTOR,
        organisation_id=ORG,
        roles=frozenset({PLATFORM_ADMINISTRATOR}),
    )

    @app.middleware("http")
    async def _inject_principal(request: Any, call_next: Any) -> Any:
        request.state.principal = principal
        return await call_next(request)

    async with _client(app) as client:
        response = await client.get("/v1/users")
    assert response.status_code == 503
