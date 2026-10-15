"""Authorization dependencies.

Two guards live here, and the difference between them is deliberate.

`require_permissions` enforces the platform's **static** matrix: the five
built-in roles and the permissions fixed to them. It is what feature 001's routes
use, and it stays because those guarantees must not change underneath them.

`require_effective_permission` asks the **decision component** about permissions
the organisation administers at runtime. It resolves the caller's effective
permissions, assembles the decision input, and lets the engine decide - it does
not decide itself. That is ADR-0011: one authority, asked every time, so an
answer cannot differ depending on which part of the platform asked.

Both deny by default, name what was missing, and fail closed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fastapi import Request

from gov.api.application.permission.decision import build_authorization_input
from gov.api.application.permission.effective import EffectivePermissionResolver
from gov.api.application.ports import AuthorizationEngine, DecisionUnavailable
from gov.api.domain.identity.permissions import missing_permissions
from gov.api.interface.errors import (
    ForbiddenProblem,
    ServiceUnavailableProblem,
    UnauthorizedProblem,
)


def require_permissions(*permissions: str) -> Callable[[Request], None]:
    """Return a dependency that requires all of the given permissions."""
    required = tuple(permissions)

    def dependency(request: Request) -> None:
        principal: Any = getattr(request.state, "principal", None)
        if principal is None:
            raise UnauthorizedProblem("the request carries no authenticated principal")

        roles = getattr(principal, "roles", ())
        missing = missing_permissions(roles, required)
        if missing:
            raise ForbiddenProblem(
                "the caller lacks the permissions required for this action",
                errors=[
                    {"code": "missing_permission", "field": "permission", "message": name}
                    for name in missing
                ],
            )

    return dependency


def require_effective_permission(
    *,
    resolver: EffectivePermissionResolver,
    engine: AuthorizationEngine,
    permission: str,
    resource: Callable[[Request], Mapping[str, Any] | None] | None = None,
    requires_resource_accountability: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[Request], Awaitable[None]]:
    """Return a dependency that asks the decision component whether to proceed.

    `resource` lets a route describe what the request is about, so an
    attribute-based rule can decide on it. The guard passes those facts through
    untouched; it never evaluates them.

    Raises at request time:
        401 when there is no authenticated principal;
        403 when the decision is a denial, naming the rules that produced it;
        503 when the decision could not be obtained, which fails closed.
    """

    async def dependency(request: Request) -> None:
        principal: Any = getattr(request.state, "principal", None)
        if principal is None:
            raise UnauthorizedProblem("the request carries no authenticated principal")

        try:
            effective = resolver.resolve(
                organisation_id=principal.organisation_id, user_id=principal.user_id
            )
        except Exception as exc:
            # Resolution could not be completed, so the request is refused rather
            # than allowed on a partial answer.
            raise ServiceUnavailableProblem(
                "effective permissions could not be resolved, so the request is refused"
            ) from exc

        decision_input = build_authorization_input(
            organisation_id=principal.organisation_id,
            user_id=principal.user_id,
            permission=permission,
            permissions=sorted(effective),
            roles=[
                {"name": role} for role in sorted(getattr(principal, "roles", ()) or ())
            ],
            resource=resource(request) if resource is not None else None,
            requires_resource_accountability=requires_resource_accountability,
            requested_at=(clock() if clock is not None else None).isoformat()
            if clock is not None
            else None,
            context={"path": request.url.path, "method": request.method},
        )

        try:
            decision = await engine.decide(decision_input)
        except DecisionUnavailable as exc:
            raise ServiceUnavailableProblem(
                f"the authorization decision could not be obtained: {exc}"
            ) from exc

        if not decision.allowed:
            raise ForbiddenProblem(
                decision.reason,
                errors=[
                    {"code": "permission_denied", "field": "permission", "message": source}
                    for source in decision.sources
                ]
                or [
                    {
                        "code": "permission_denied",
                        "field": "permission",
                        "message": f"the caller does not hold {permission}",
                    }
                ],
            )

    return dependency


def require_effective_permission_from_state(
    permission: str,
    *,
    resource: Callable[[Request], Mapping[str, Any] | None] | None = None,
    requires_resource_accountability: bool = False,
) -> Callable[[Request], Awaitable[None]]:
    """Return a dependency that resolves the decision components per request.

    Routes are defined at import time, before the application exists, so the
    resolver and the engine are taken from the application state when the request
    arrives. A deployment that has not wired them refuses every request it would
    have had to decide: fail closed, never fall back to a static check.
    """

    async def dependency(request: Request) -> None:
        resolver = getattr(request.app.state, "permission_resolver", None)
        engine = getattr(request.app.state, "authorization_engine", None)
        if resolver is None or engine is None:
            raise ServiceUnavailableProblem(
                "the authorization components are not configured for this "
                "deployment, so the request is refused"
            )

        guard = require_effective_permission(
            resolver=resolver,
            engine=engine,
            permission=permission,
            resource=resource,
            requires_resource_accountability=requires_resource_accountability,
        )
        await guard(request)

    return dependency
