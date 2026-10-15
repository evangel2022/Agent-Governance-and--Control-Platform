"""Unit tests for the role permission model (T024)."""

from __future__ import annotations

import pytest

from gov.api.domain.identity import permissions as perms


def test_all_five_roles_are_defined() -> None:
    assert {
        perms.PLATFORM_ADMINISTRATOR,
        perms.AGENT_DEVELOPER,
        perms.SECURITY_COMPLIANCE,
        perms.BUSINESS_APPROVER,
        perms.AUDITOR,
    } == perms.ROLES


def test_every_role_grant_is_a_known_permission() -> None:
    for role, granted in perms.ROLE_PERMISSIONS.items():
        unknown = granted - perms.PERMISSIONS
        assert not unknown, f"{role} grants unknown permissions: {unknown}"


def test_administrator_cannot_approve() -> None:
    """Approval authority is a distinct grant, not implied by admin status."""
    assert perms.has_permission([perms.PLATFORM_ADMINISTRATOR], perms.APPROVAL_DECIDE) is False


def test_business_approver_can_approve() -> None:
    assert perms.has_permission([perms.BUSINESS_APPROVER], perms.APPROVAL_DECIDE) is True


def test_business_approver_cannot_write_policies() -> None:
    assert perms.has_permission([perms.BUSINESS_APPROVER], perms.POLICY_PUBLISH) is False
    assert perms.has_permission([perms.BUSINESS_APPROVER], perms.POLICY_WRITE) is False


def test_security_compliance_can_publish_policy_but_cannot_approve() -> None:
    assert perms.has_permission([perms.SECURITY_COMPLIANCE], perms.POLICY_PUBLISH) is True
    assert perms.has_permission([perms.SECURITY_COMPLIANCE], perms.APPROVAL_DECIDE) is False


def test_auditor_can_read_and_export_audit_only() -> None:
    assert perms.has_permission([perms.AUDITOR], perms.AUDIT_READ) is True
    assert perms.has_permission([perms.AUDITOR], perms.AUDIT_EXPORT) is True
    assert perms.has_permission([perms.AUDITOR], perms.REGISTRY_WRITE) is False
    assert perms.has_permission([perms.AUDITOR], perms.POLICY_WRITE) is False


def test_agent_developer_cannot_retire_or_publish_policy() -> None:
    assert perms.has_permission([perms.AGENT_DEVELOPER], perms.REGISTRY_WRITE) is True
    assert perms.has_permission([perms.AGENT_DEVELOPER], perms.REGISTRY_RETIRE) is False
    assert perms.has_permission([perms.AGENT_DEVELOPER], perms.POLICY_PUBLISH) is False


def test_unknown_permission_is_denied_by_default() -> None:
    assert perms.has_permission([perms.PLATFORM_ADMINISTRATOR], "registry.teleport") is False


def test_unknown_role_grants_nothing() -> None:
    assert perms.permissions_for(["root"]) == frozenset()
    assert perms.has_permission(["root"], perms.AUDIT_READ) is False


def test_roles_combine() -> None:
    combined = perms.permissions_for([perms.AUDITOR, perms.BUSINESS_APPROVER])
    assert perms.AUDIT_EXPORT in combined
    assert perms.APPROVAL_DECIDE in combined


@pytest.mark.parametrize(
    ("role", "forbidden"),
    [
        (perms.PLATFORM_ADMINISTRATOR, perms.POLICY_PUBLISH),
        (perms.AGENT_DEVELOPER, perms.APPROVAL_DECIDE),
        (perms.SECURITY_COMPLIANCE, perms.REGISTRY_WRITE),
        (perms.BUSINESS_APPROVER, perms.AUDIT_EXPORT),
        (perms.AUDITOR, perms.APPROVAL_DECIDE),
    ],
)
def test_separation_of_duties_per_role(role: str, forbidden: str) -> None:
    assert perms.has_permission([role], forbidden) is False


def test_missing_permissions_reports_every_gap() -> None:
    missing = perms.missing_permissions(
        [perms.AUDITOR], [perms.AUDIT_READ, perms.POLICY_PUBLISH, perms.APPROVAL_DECIDE]
    )
    assert missing == (perms.POLICY_PUBLISH, perms.APPROVAL_DECIDE)
