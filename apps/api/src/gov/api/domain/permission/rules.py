"""The rules a grant must satisfy.

Implements the parts of the specification that are pure decisions rather than
orchestration: scope consistency (FR-010), expiry and revocation (FR-011,
FR-020), and the immutability of the five built-in roles (FR-031).

Everything here is expressed as a function over values, so the same rule can be
applied when a grant is created, when it is read back, and when a decision is
made - and cannot drift between those three moments.

**A schema consequence worth noting.** `role.code` is a PostgreSQL enum of the
five built-in codes and is `NOT NULL`, so an organisation cannot create a role
that carries a code. Custom roles therefore hold a NULL code, and a built-in role
is identified by `organisation_id IS NULL`. Revision `0005_permission_center` must
drop the `NOT NULL` on `role.code` for that to be possible.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from gov.api.domain.identity.permissions import ROLES

#: The five codes the platform guarantees. A role carrying one of these with no
#: organisation is a built-in role and cannot be edited or retired.
BUILTIN_ROLE_CODES: frozenset[str] = ROLES


class PermissionRuleError(ValueError):
    """A grant violates a rule."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ScopeType(StrEnum):
    """What an assignment is limited to."""

    ORGANISATION = "organisation"
    AGENT = "agent"
    TOOL = "tool"


class RoleStatus(StrEnum):
    """A role's lifecycle state. Retired, never deleted (FR-005)."""

    ACTIVE = "active"
    RETIRED = "retired"


class AssignmentState(StrEnum):
    """Whether an assignment currently grants anything."""

    EFFECTIVE = "effective"
    REVOKED = "revoked"
    EXPIRED = "expired"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PermissionRuleError(
            "naive_datetime",
            f"{field_name} must be timezone-aware so windows are comparable",
        )
    return value


def validate_scope(*, scope_type: str, scope_id: str | None) -> None:
    """Check that a scope names an id exactly when it should.

    Raises:
        PermissionRuleError: for an unknown scope type, an organisation-scoped
            grant that names an id, or any other scope that does not.
    """
    if scope_type not in {member.value for member in ScopeType}:
        raise PermissionRuleError(
            "unknown_scope_type", f"unknown scope type: {scope_type!r}"
        )
    if scope_type == ScopeType.ORGANISATION:
        if scope_id is not None:
            raise PermissionRuleError(
                "scope_id_not_allowed",
                "an organisation-scoped grant covers the whole organisation and "
                "must not name an id",
            )
        return
    if scope_id is None:
        raise PermissionRuleError(
            "scope_id_required",
            f"a {scope_type}-scoped grant must name the {scope_type} it covers",
        )


def assignment_state(
    *,
    revoked_at: datetime | None,
    expires_at: datetime | None,
    at: datetime,
) -> AssignmentState:
    """Return whether an assignment still grants anything at a given moment.

    Revocation wins over expiry when both are present, because a revoked grant
    must never be described as merely lapsed.
    """
    _require_aware(at, "at")
    if revoked_at is not None:
        _require_aware(revoked_at, "revoked_at")
        return AssignmentState.REVOKED
    if expires_at is not None:
        _require_aware(expires_at, "expires_at")
        if at > expires_at:
            return AssignmentState.EXPIRED
    return AssignmentState.EFFECTIVE


def is_effective(
    *,
    revoked_at: datetime | None,
    expires_at: datetime | None,
    at: datetime,
) -> bool:
    """Whether an assignment grants its permissions at a given moment."""
    return (
        assignment_state(revoked_at=revoked_at, expires_at=expires_at, at=at)
        is AssignmentState.EFFECTIVE
    )


def is_builtin_role(*, organisation_id: str | None) -> bool:
    """Whether a role row is one of the platform's five built-in roles."""
    return organisation_id is None


def assert_role_is_mutable(*, organisation_id: str | None, role_name: str) -> None:
    """Refuse any change to a built-in role (FR-031).

    Raises:
        PermissionRuleError: when the role has no organisation, which is how the
            built-in roles are identified.
    """
    if is_builtin_role(organisation_id=organisation_id):
        raise PermissionRuleError(
            "builtin_role_immutable",
            f"{role_name!r} is a built-in role and cannot be amended or retired",
        )


def assert_not_last_authority(*, remaining_managers: int, role_name: str) -> None:
    """Refuse a change that would leave nobody able to manage permissions (FR-027).

    Raises:
        PermissionRuleError: when no other holder of the managing permission
            would remain.
    """
    if remaining_managers <= 0:
        raise PermissionRuleError(
            "last_authority",
            f"refused: removing {role_name!r} would leave the organisation with "
            "nobody able to manage permissions",
        )
