"""Unit tests for the authorization dependency (T025)."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from gov.api.domain.identity import permissions as perms
from gov.api.interface.errors import ForbiddenProblem, UnauthorizedProblem
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.oidc import Principal


def _request(principal: Principal | None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/audit-events",
        "raw_path": b"/v1/audit-events",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


def _principal(*roles: str) -> Principal:
    return Principal(
        subject="user-1",
        user_id="user-1",
        organisation_id="org-1",
        roles=frozenset(roles),
    )


def test_permitted_caller_passes() -> None:
    dependency = require_permissions(perms.AUDIT_READ)
    dependency(_request(_principal(perms.AUDITOR)))


def test_missing_principal_is_unauthorized() -> None:
    dependency = require_permissions(perms.AUDIT_READ)
    with pytest.raises(UnauthorizedProblem):
        dependency(_request(None))


def test_caller_without_the_permission_is_forbidden() -> None:
    dependency = require_permissions(perms.POLICY_PUBLISH)
    with pytest.raises(ForbiddenProblem) as excinfo:
        dependency(_request(_principal(perms.AUDITOR)))
    assert excinfo.value.status == 403
    assert excinfo.value.code == "forbidden"


def test_forbidden_error_names_every_missing_permission() -> None:
    dependency = require_permissions(perms.POLICY_PUBLISH, perms.APPROVAL_DECIDE)
    with pytest.raises(ForbiddenProblem) as excinfo:
        dependency(_request(_principal(perms.AUDITOR)))
    reported = {item["message"] for item in excinfo.value.errors}
    assert reported == {perms.POLICY_PUBLISH, perms.APPROVAL_DECIDE}


def test_all_required_permissions_must_be_granted() -> None:
    dependency = require_permissions(perms.AUDIT_READ, perms.POLICY_PUBLISH)
    with pytest.raises(ForbiddenProblem):
        dependency(_request(_principal(perms.AUDITOR)))


def test_combined_roles_satisfy_combined_requirements() -> None:
    dependency = require_permissions(perms.AUDIT_EXPORT, perms.APPROVAL_DECIDE)
    dependency(_request(_principal(perms.AUDITOR, perms.BUSINESS_APPROVER)))


def test_administrator_still_cannot_approve() -> None:
    dependency = require_permissions(perms.APPROVAL_DECIDE)
    with pytest.raises(ForbiddenProblem):
        dependency(_request(_principal(perms.PLATFORM_ADMINISTRATOR)))


def test_dependency_with_no_requirements_always_passes() -> None:
    dependency = require_permissions()
    dependency(_request(_principal(perms.AUDITOR)))
