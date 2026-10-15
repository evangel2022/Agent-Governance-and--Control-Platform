"""Shared setup for the verification suites (T038, T040, T041).

Two applications are needed. The Permission Center's own administration routes
are guarded by the built-in matrix; the Agent Registry routes are guarded by the
decision component, which is where fail-closed and deny-by-default are observable.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from _inmemory import (
    InMemoryAuthorizationEngine,
    InMemoryStore,
    InMemoryUnitOfWork,
    assign_builtin_role,
    seed_builtin_roles,
)
from fastapi import FastAPI

from gov.api.application.audit.denials import DenialRecorder
from gov.api.application.audit.queries import AuditQueryService
from gov.api.application.permission.assignments import AssignmentService
from gov.api.application.permission.effective import EffectivePermissionResolver
from gov.api.application.permission.roles import RoleService
from gov.api.application.permission.users import UserService
from gov.api.application.ports import UserRecord
from gov.api.application.registry.service import RegistryService
from gov.api.domain.identity.permissions import PLATFORM_ADMINISTRATOR
from gov.api.interface.security.oidc import Principal
from gov.api.main import create_app

ORG = "org-1"
ACTOR = "user-admin"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

#: Registry routes, which enforce through the decision component.
REGISTRY_SURFACE: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/v1/agents", None),
    ("POST", "/v1/agents", {"name": "ap-reconciler", "owner_user_id": ACTOR}),
    ("GET", "/v1/agents/{agent_id}", None),
    ("PATCH", "/v1/agents/{agent_id}", {"description": "updated"}),
    ("GET", "/v1/agents/{agent_id}/versions", None),
    (
        "POST",
        "/v1/agents/{agent_id}/versions",
        {"version": "1.0.0", "owner_user_id": ACTOR},
    ),
    ("POST", "/v1/agents/{agent_id}/versions/1.0.0/release", None),
)

#: Permission Center routes, which enforce through the built-in matrix.
PERMISSION_SURFACE: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/v1/users", None),
    ("GET", "/v1/permissions", None),
    ("GET", "/v1/roles", None),
    ("POST", "/v1/roles", {"name": "owner", "description": "Owns things."}),
    ("GET", "/v1/role-assignments", None),
)


def resolve_path(path: str) -> str:
    """Substitute the identifiers the routes expect."""
    return path.replace("{agent_id}", "agent-1")


def registry_app(
    *,
    role_code: str = PLATFORM_ADMINISTRATOR,
    engine: InMemoryAuthorizationEngine | None = None,
    wire_components: bool = True,
    authenticate: bool = True,
    denial_recorder: DenialRecorder | None = None,
) -> tuple[FastAPI, InMemoryStore]:
    """Build an application whose registry routes enforce through the engine."""
    store = InMemoryStore()
    counter = itertools.count(1)
    store.users[ACTOR] = UserRecord(
        id=ACTOR,
        organisation_id=ORG,
        external_subject="sub-admin",
        display_name="Ada Administrator",
        email="ada@example.invalid",
    )
    seed_builtin_roles(store)
    if role_code:
        assign_builtin_role(
            store, organisation_id=ORG, user_id=ACTOR, code=role_code
        )

    app = create_app(
        registry_service=RegistryService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"id-{next(counter)}",
        ),
        denial_recorder=denial_recorder,
    )
    if wire_components:
        app.state.permission_resolver = EffectivePermissionResolver(
            lambda: InMemoryUnitOfWork(store), clock=lambda: NOW
        )
        app.state.authorization_engine = engine or InMemoryAuthorizationEngine()

    if authenticate:
        principal = Principal(
            subject=ACTOR,
            user_id=ACTOR,
            organisation_id=ORG,
            roles=frozenset({role_code}) if role_code else frozenset(),
        )

        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = principal
            return await call_next(request)

    return app, store


def permission_app(
    *,
    authenticate: bool = True,
    roles: frozenset[str] = frozenset({PLATFORM_ADMINISTRATOR}),
    denial_recorder: DenialRecorder | None = None,
    wire_audit: bool = False,
) -> tuple[FastAPI, InMemoryStore]:
    """Build an application for the Permission Center's own routes."""
    store = InMemoryStore()
    counter = itertools.count(1)
    app = create_app(
        user_service=UserService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"user-{next(counter)}",
        ),
        role_service=RoleService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"role-{next(counter)}",
        ),
        assignment_service=AssignmentService(
            lambda: InMemoryUnitOfWork(store),
            clock=lambda: NOW,
            new_id=lambda: f"assignment-{next(counter)}",
        ),
        audit_service=(
            AuditQueryService(lambda: InMemoryUnitOfWork(store))
            if wire_audit
            else None
        ),
        denial_recorder=denial_recorder,
    )
    if authenticate:
        principal = Principal(
            subject=ACTOR,
            user_id=ACTOR,
            organisation_id=ORG,
            roles=roles,
        )

        @app.middleware("http")
        async def _inject_principal(request: Any, call_next: Any) -> Any:
            request.state.principal = principal
            return await call_next(request)

    return app, store
