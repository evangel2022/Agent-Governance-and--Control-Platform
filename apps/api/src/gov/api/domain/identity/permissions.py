"""Role-based permission model.

Implements FR-001 to FR-004 and constitution Principle V (least privilege).

The model is deny-by-default: a permission that is not explicitly granted to one
of the caller's roles is refused. approval.decide is deliberately not implied by
administrative status, so approval authority is a distinct grant (FR-003, FR-004).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

PLATFORM_ADMINISTRATOR = "platform_administrator"
AGENT_DEVELOPER = "agent_developer"
SECURITY_COMPLIANCE = "security_compliance"
BUSINESS_APPROVER = "business_approver"
AUDITOR = "auditor"

#: The five core user types from the specification.
ROLES: frozenset[str] = frozenset(
    {
        PLATFORM_ADMINISTRATOR,
        AGENT_DEVELOPER,
        SECURITY_COMPLIANCE,
        BUSINESS_APPROVER,
        AUDITOR,
    }
)

REGISTRY_READ = "registry.read"
REGISTRY_WRITE = "registry.write"
REGISTRY_RETIRE = "registry.retire"
#: Act on any Agent, regardless of who is accountable for it. Held only by the
#: Platform Administrator, which is what makes the accountability rule in
#: `deploy/policy/authorization.rego` a policy decision rather than a hard-coded
#: exception in the control plane.
REGISTRY_WRITE_ANY = "registry.write_any"
POLICY_READ = "policy.read"
POLICY_WRITE = "policy.write"
POLICY_PUBLISH = "policy.publish"
APPROVAL_READ = "approval.read"
APPROVAL_DECIDE = "approval.decide"
AUDIT_READ = "audit.read"
AUDIT_EXPORT = "audit.export"
RELEASE_READ = "release.read"
RELEASE_WRITE = "release.write"
EVALUATION_READ = "evaluation.read"
EVALUATION_WRITE = "evaluation.write"
DASHBOARD_READ = "dashboard.read"
IDENTITY_MANAGE = "identity.manage"
RISK_RAISE = "risk.raise"

#: Every permission the platform recognises. Anything outside this set is
#: refused even if a grant list were somehow to contain it, so a typo cannot
#: widen access.
PERMISSIONS: frozenset[str] = frozenset(
    {
        REGISTRY_READ,
        REGISTRY_WRITE,
        REGISTRY_RETIRE,
        REGISTRY_WRITE_ANY,
        POLICY_READ,
        POLICY_WRITE,
        POLICY_PUBLISH,
        APPROVAL_READ,
        APPROVAL_DECIDE,
        AUDIT_READ,
        AUDIT_EXPORT,
        RELEASE_READ,
        RELEASE_WRITE,
        EVALUATION_READ,
        EVALUATION_WRITE,
        DASHBOARD_READ,
        IDENTITY_MANAGE,
        RISK_RAISE,
    }
)

ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    PLATFORM_ADMINISTRATOR: frozenset(
        {
            REGISTRY_READ,
            REGISTRY_WRITE,
            REGISTRY_RETIRE,
            REGISTRY_WRITE_ANY,
            POLICY_READ,
            APPROVAL_READ,
            AUDIT_READ,
            RELEASE_READ,
            RELEASE_WRITE,
            EVALUATION_READ,
            DASHBOARD_READ,
            IDENTITY_MANAGE,
            RISK_RAISE,
        }
    ),
    AGENT_DEVELOPER: frozenset(
        {
            REGISTRY_READ,
            REGISTRY_WRITE,
            POLICY_READ,
            RELEASE_READ,
            RELEASE_WRITE,
            EVALUATION_READ,
            EVALUATION_WRITE,
            DASHBOARD_READ,
        }
    ),
    SECURITY_COMPLIANCE: frozenset(
        {
            REGISTRY_READ,
            POLICY_READ,
            POLICY_WRITE,
            POLICY_PUBLISH,
            AUDIT_READ,
            AUDIT_EXPORT,
            EVALUATION_READ,
            EVALUATION_WRITE,
            DASHBOARD_READ,
            RISK_RAISE,
        }
    ),
    BUSINESS_APPROVER: frozenset(
        {
            REGISTRY_READ,
            APPROVAL_READ,
            APPROVAL_DECIDE,
            DASHBOARD_READ,
        }
    ),
    AUDITOR: frozenset(
        {
            REGISTRY_READ,
            AUDIT_READ,
            AUDIT_EXPORT,
            DASHBOARD_READ,
        }
    ),
}


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    """Return the union of the permissions granted by the given roles.

    Unknown roles contribute nothing, so an unrecognised role cannot widen
    access.
    """
    granted: set[str] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


def has_permission(roles: Iterable[str], permission: str) -> bool:
    """Return whether the roles grant the permission. Deny by default."""
    if permission not in PERMISSIONS:
        return False
    return permission in permissions_for(roles)


def missing_permissions(roles: Iterable[str], required: Iterable[str]) -> tuple[str, ...]:
    """Return the required permissions that the roles do not grant."""
    granted = permissions_for(roles)
    return tuple(permission for permission in required if permission not in granted)
