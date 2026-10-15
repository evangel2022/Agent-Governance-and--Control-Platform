"""The routes the Permission Center owns, as data.

Shared by the security matrix and the auditor read-only suite. Each entry names
the method, the path (with its placeholders), the body the route needs to reach
its guard, and the permission the guard requires. The permission is carried
explicitly so a suite can decide whether a role *should* be refused without
re-deriving that from the matrix under test.
"""
from __future__ import annotations

from typing import Any

#: Path prefixes this feature owns, used to prove the matrix covers everything
#: the application declares under them.
OWNED_PREFIXES: tuple[str, ...] = (
    "/v1/users",
    "/v1/permissions",
    "/v1/roles",
    "/v1/role-assignments",
    "/v1/audit-events",
)

IDENTITY_MANAGE = "identity.manage"
AUDIT_READ = "audit.read"

#: method, path, body, required permission.
SURFACE: tuple[tuple[str, str, dict[str, Any] | None, str], ...] = (
    ("GET", "/v1/users", None, IDENTITY_MANAGE),
    (
        "POST",
        "/v1/users",
        {
            "external_subject": "sub-1",
            "display_name": "Dana Developer",
            "email": "dana@example.invalid",
        },
        IDENTITY_MANAGE,
    ),
    ("GET", "/v1/users/{user_id}", None, IDENTITY_MANAGE),
    ("PATCH", "/v1/users/{user_id}", {"display_name": "Renamed"}, IDENTITY_MANAGE),
    ("GET", "/v1/permissions", None, IDENTITY_MANAGE),
    ("GET", "/v1/roles", None, IDENTITY_MANAGE),
    ("POST", "/v1/roles", {"name": "owner", "description": "Owns things."}, IDENTITY_MANAGE),
    ("GET", "/v1/roles/{role_id}", None, IDENTITY_MANAGE),
    ("PATCH", "/v1/roles/{role_id}", {"description": "Renamed"}, IDENTITY_MANAGE),
    ("GET", "/v1/roles/{role_id}/permissions", None, IDENTITY_MANAGE),
    (
        "POST",
        "/v1/roles/{role_id}/permissions",
        {"permission_name": "registry.read"},
        IDENTITY_MANAGE,
    ),
    (
        "POST",
        "/v1/roles/{role_id}/permissions/{permission_name}/unbind",
        {"reason": "narrowed"},
        IDENTITY_MANAGE,
    ),
    ("GET", "/v1/role-assignments", None, IDENTITY_MANAGE),
    (
        "POST",
        "/v1/role-assignments",
        {
            "user_id": "user-1",
            "role_id": "role-1",
            "scope_type": "organisation",
            "reason": "owns these Agents",
        },
        IDENTITY_MANAGE,
    ),
    (
        "POST",
        "/v1/role-assignments/{assignment_id}/revoke",
        {"reason": "no longer needed"},
        IDENTITY_MANAGE,
    ),
    ("GET", "/v1/agents/{agent_id}/responsibility", None, IDENTITY_MANAGE),
    (
        "POST",
        "/v1/agents/{agent_id}/responsibility",
        {"accountable_user_id": "user-1", "reason": "moved teams"},
        IDENTITY_MANAGE,
    ),
    ("GET", "/v1/audit-events", None, AUDIT_READ),
    ("GET", "/v1/audit-events/{target_type}/{target_id}", None, AUDIT_READ),
)

#: The methods that change something. A refusal on one of these is a write the
#: platform declined to perform.
WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def resolve(path: str) -> str:
    """Substitute the identifiers the routes expect."""
    return (
        path.replace("{user_id}", "user-1")
        .replace("{role_id}", "role-1")
        .replace("{permission_name}", "registry.read")
        .replace("{assignment_id}", "assignment-1")
        .replace("{agent_id}", "agent-1")
        .replace("{target_type}", "role")
        .replace("{target_id}", "role-1")
    )
