"""Unit tests for the permission catalogue and grant rules (T002, T007)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gov.api.domain.identity import permissions as identity
from gov.api.domain.permission.catalogue import (
    CATALOGUE,
    NAME_PATTERN,
    PermissionDefinition,
    PermissionNameError,
    UnknownPermissionError,
    by_resource,
    get,
    resources,
)
from gov.api.domain.permission.rules import (
    BUILTIN_ROLE_CODES,
    AssignmentState,
    PermissionRuleError,
    ScopeType,
    assert_not_last_authority,
    assert_role_is_mutable,
    assignment_state,
    is_builtin_role,
    is_effective,
    validate_scope,
)

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------- catalogue


def test_every_catalogued_name_matches_the_pattern() -> None:
    for item in CATALOGUE:
        assert NAME_PATTERN.match(item.name), item.name


def test_every_catalogued_permission_describes_what_it_authorises() -> None:
    for item in CATALOGUE:
        assert item.description.strip().endswith("."), item.name
        # A phrase, not a restatement of the name.
        assert " " in item.description, item.name
        assert len(item.description) >= 10, item.name


def test_catalogue_has_no_duplicate_names() -> None:
    names = [item.name for item in CATALOGUE]
    assert len(names) == len(set(names))


def test_catalogue_documents_every_permission_the_platform_enforces() -> None:
    """The catalogue must not lag the permission set it describes."""
    undocumented = identity.PERMISSIONS - {item.name for item in CATALOGUE}
    assert undocumented == set()


def test_the_catalogue_adds_only_the_known_permissions() -> None:
    """Anything beyond the platform's set is a deliberate addition, not drift."""
    extra = {item.name for item in CATALOGUE} - identity.PERMISSIONS
    assert extra == set()


def test_every_catalogued_permission_is_one_the_platform_enforces() -> None:
    """The two sets are identical: the catalogue describes, it does not invent."""
    assert {item.name for item in CATALOGUE} == identity.PERMISSIONS


def test_resource_and_action_are_derived_from_the_name() -> None:
    definition = get("registry.retire")
    assert definition.resource == "registry"
    assert definition.action == "retire"


def test_an_unknown_permission_is_refused() -> None:
    with pytest.raises(UnknownPermissionError):
        get("registry.teleport")


def test_by_resource_returns_only_that_family() -> None:
    registry = by_resource("registry")
    assert [item.name for item in registry] == [
        "registry.read",
        "registry.write",
        "registry.retire",
        "registry.write_any",
    ]
    assert by_resource("nonexistent") == ()


def test_resources_are_listed_once_each() -> None:
    listed = resources()
    assert len(listed) == len(set(listed))
    assert "registry" in listed and "approval" in listed


@pytest.mark.parametrize("name", ["Registry.Read", "registry", "registry.", ".read", "a b"])
def test_a_malformed_name_is_rejected_at_definition_time(name: str) -> None:
    with pytest.raises(PermissionNameError):
        PermissionDefinition(name=name, description="A sufficiently long description.")


def test_a_permission_without_a_description_is_rejected() -> None:
    with pytest.raises(PermissionNameError):
        PermissionDefinition(name="registry.read", description="   ")


# -------------------------------------------------------------------- scope


def test_an_organisation_scope_must_not_name_an_id() -> None:
    validate_scope(scope_type=ScopeType.ORGANISATION, scope_id=None)
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_scope(scope_type=ScopeType.ORGANISATION, scope_id="agent-1")
    assert excinfo.value.code == "scope_id_not_allowed"


@pytest.mark.parametrize("scope", [ScopeType.AGENT, ScopeType.TOOL])
def test_a_resource_scope_must_name_an_id(scope: ScopeType) -> None:
    validate_scope(scope_type=scope, scope_id="thing-1")
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_scope(scope_type=scope, scope_id=None)
    assert excinfo.value.code == "scope_id_required"


def test_an_unknown_scope_type_is_refused() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        validate_scope(scope_type="galaxy", scope_id="x")
    assert excinfo.value.code == "unknown_scope_type"


# --------------------------------------------------------------- assignment


def test_an_assignment_without_a_window_is_effective() -> None:
    state = assignment_state(revoked_at=None, expires_at=None, at=NOW)
    assert state is AssignmentState.EFFECTIVE
    assert is_effective(revoked_at=None, expires_at=None, at=NOW) is True


def test_an_assignment_inside_its_window_is_effective() -> None:
    assert is_effective(revoked_at=None, expires_at=NOW + timedelta(hours=1), at=NOW)


def test_an_assignment_past_its_window_is_expired() -> None:
    state = assignment_state(
        revoked_at=None, expires_at=NOW - timedelta(seconds=1), at=NOW
    )
    assert state is AssignmentState.EXPIRED


def test_expiry_is_inclusive_of_the_boundary() -> None:
    assert is_effective(revoked_at=None, expires_at=NOW, at=NOW)


def test_a_revoked_assignment_is_revoked_even_when_it_also_lapsed() -> None:
    """A revoked grant must never be described as merely expired."""
    state = assignment_state(
        revoked_at=NOW - timedelta(minutes=1),
        expires_at=NOW - timedelta(hours=1),
        at=NOW,
    )
    assert state is AssignmentState.REVOKED
    assert is_effective(
        revoked_at=NOW - timedelta(minutes=1),
        expires_at=NOW - timedelta(hours=1),
        at=NOW,
    ) is False


def test_naive_times_are_rejected() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        assignment_state(
            revoked_at=None, expires_at=None, at=datetime(2026, 10, 14, 9, 0)
        )
    assert excinfo.value.code == "naive_datetime"


# ------------------------------------------------------------ built-in roles


def test_the_five_builtin_codes_are_the_platform_roles() -> None:
    assert BUILTIN_ROLE_CODES == identity.ROLES
    assert len(BUILTIN_ROLE_CODES) == 5


def test_a_role_without_an_organisation_is_built_in() -> None:
    assert is_builtin_role(organisation_id=None) is True
    assert is_builtin_role(organisation_id="org-1") is False


def test_a_builtin_role_cannot_be_amended_or_retired() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        assert_role_is_mutable(organisation_id=None, role_name="Auditor")
    assert excinfo.value.code == "builtin_role_immutable"


def test_an_organisation_role_can_be_amended() -> None:
    assert_role_is_mutable(organisation_id="org-1", role_name="erp-invoice-owner")


# ------------------------------------------------------------- last authority


def test_removing_the_last_authority_is_refused() -> None:
    with pytest.raises(PermissionRuleError) as excinfo:
        assert_not_last_authority(remaining_managers=0, role_name="Platform Administrator")
    assert excinfo.value.code == "last_authority"


def test_removing_an_authority_is_allowed_while_another_remains() -> None:
    assert_not_last_authority(remaining_managers=1, role_name="erp-invoice-owner")
