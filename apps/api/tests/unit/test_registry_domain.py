"""Unit tests for registry entities and validation (T039, US1 scenario 4)."""

from __future__ import annotations

import pytest

from gov.api.domain.classification import CONFIDENTIAL, PUBLIC
from gov.api.domain.registry.entities import (
    DESCRIPTION_MAX,
    Agent,
    AgentVersion,
    DomainValidationError,
    Tool,
    ToolPermission,
    derive_sandbox_class,
    validate_version,
)


def _permission(**overrides: object) -> ToolPermission:
    payload: dict[str, object] = {
        "resource_type": "erp.invoice",
        "action": "read",
        "data_class": PUBLIC,
    }
    payload.update(overrides)
    return ToolPermission(**payload)  # type: ignore[arg-type]


def _tool(**overrides: object) -> Tool:
    payload: dict[str, object] = {
        "name": "invoice-reader",
        "risk_level": "low",
        "risk_basis": "read-only access to non-sensitive invoice metadata",
        "adapter_ref": "erp.invoice.read",
        "permissions": (_permission(),),
    }
    payload.update(overrides)
    return Tool(**payload)  # type: ignore[arg-type]


def test_a_complete_agent_is_accepted() -> None:
    agent = Agent(name="ap-reconciler", owner_user_id="user-1")
    assert agent.status == "draft"


@pytest.mark.parametrize("name", ["", "   ", None])
def test_agent_requires_a_name(name: object) -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        Agent(name=name, owner_user_id="user-1")  # type: ignore[arg-type]
    assert excinfo.value.field == "name"


def test_agent_requires_an_owner() -> None:
    """US1 scenario 4: a registration missing its owner creates nothing."""
    with pytest.raises(DomainValidationError) as excinfo:
        Agent(name="ap-reconciler", owner_user_id="")
    assert excinfo.value.field == "owner_user_id"


def test_agent_name_length_is_bounded() -> None:
    with pytest.raises(DomainValidationError):
        Agent(name="x" * 201, owner_user_id="user-1")


def test_agent_description_length_is_bounded() -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        Agent(
            name="ok",
            owner_user_id="user-1",
            description="x" * (DESCRIPTION_MAX + 1),
        )
    assert excinfo.value.field == "description"


def test_agent_status_must_be_a_known_lifecycle_state() -> None:
    with pytest.raises(DomainValidationError):
        Agent(name="ok", owner_user_id="user-1", status="running")


@pytest.mark.parametrize("version", ["1.0.0", "2.3.4", "1.0.0-rc1", "1.0.0+build.7"])
def test_valid_versions_are_accepted(version: str) -> None:
    assert validate_version(version) == version


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "", "latest", "1.0.0.0"])
def test_invalid_versions_are_rejected(version: str) -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        validate_version(version)
    assert excinfo.value.field == "version"


def test_agent_version_requires_an_owner() -> None:
    with pytest.raises(DomainValidationError):
        AgentVersion(agent_id="agent-1", version="1.0.0", owner_user_id="")


def test_tool_without_permissions_is_rejected() -> None:
    """US1 scenario 4: a Tool registration missing its permission set is refused."""
    with pytest.raises(DomainValidationError) as excinfo:
        _tool(permissions=())
    assert excinfo.value.field == "permissions"


def test_tool_without_a_risk_basis_is_rejected() -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        _tool(risk_basis="")
    assert excinfo.value.field == "risk_basis"


def test_tool_risk_level_must_be_known() -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        _tool(risk_level="catastrophic")
    assert excinfo.value.field == "risk_level"


def test_permission_action_must_be_known() -> None:
    with pytest.raises(DomainValidationError) as excinfo:
        _permission(action="delete_everything")
    assert excinfo.value.field == "action"


def test_permission_must_declare_a_known_data_class() -> None:
    with pytest.raises(ValueError):
        _permission(data_class="secret")


def test_permission_accepts_a_sensitive_class() -> None:
    permission = _permission(data_class=CONFIDENTIAL)
    assert permission.data_class == CONFIDENTIAL


@pytest.mark.parametrize(
    ("risk_level", "expected"),
    [
        ("low", "shared"),
        ("medium", "shared"),
        ("high", "dedicated"),
        ("critical", "dedicated"),
    ],
)
def test_sandbox_class_follows_risk(risk_level: str, expected: str) -> None:
    assert derive_sandbox_class(risk_level) == expected


def test_tool_exposes_its_sandbox_class_and_risk_flag() -> None:
    high = _tool(risk_level="high")
    assert high.requires_sandbox_class == "dedicated"
    assert high.is_high_risk is True

    low = _tool(risk_level="low")
    assert low.requires_sandbox_class == "shared"
    assert low.is_high_risk is False


def test_derive_sandbox_class_rejects_an_unknown_risk_level() -> None:
    with pytest.raises(DomainValidationError):
        derive_sandbox_class("enormous")
