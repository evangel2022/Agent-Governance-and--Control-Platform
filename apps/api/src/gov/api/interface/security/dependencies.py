"""Shared HTTP dependencies: the authenticated principal and configured services.

These were previously duplicated per router. Two copies of an authentication
dependency is where divergence starts, so they live here and every router imports
them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from gov.api.interface.errors import ServiceUnavailableProblem, UnauthorizedProblem
from gov.api.interface.security.oidc import Principal


def get_principal(request: Request) -> Principal:
    """Return the authenticated caller, or refuse the request.

    The principal is placed on the request by the authentication middleware.
    Nothing else may construct one, so a route cannot accidentally accept an
    unauthenticated caller.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthorizedProblem("the request carries no authenticated principal")
    return principal


def get_clock() -> Callable[[], datetime]:
    """Return the clock endpoints stamp server-side timestamps with."""
    return lambda: datetime.now(UTC)


def service_dependency(attribute: str, label: str) -> Callable[[Request], Any]:
    """Build a dependency that resolves a service from the application state.

    A missing service is a 503 rather than a 404: the endpoint exists, the
    deployment simply has not been wired yet, and saying so plainly is more
    useful than pretending the route is absent.
    """

    def dependency(request: Request) -> Any:
        service = getattr(request.app.state, attribute, None)
        if service is None:
            raise ServiceUnavailableProblem(
                f"the {label} service is not configured for this deployment"
            )
        return service

    return dependency
