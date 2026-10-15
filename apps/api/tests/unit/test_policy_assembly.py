"""Unit tests for policy input assembly and risk rules (T045, FR-016)."""

from __future__ import annotations

import pytest

from gov.api.domain.policy.assembly import (
    PolicyInputError,
    assemble_decision_input,
    escalate_risk,
    requires_approval,
)


def _assemble(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "organisation_id": "org-1",
        "actor": "agent-identity-1",
        "agent_version_id": "agent-version-1",
        "tool_id": "tool-1",
        "environment": "prod",
        "risk_level": "low",
        "policies": [],
    }
    payload.update(overrides)
    return assemble_decision_input(**payload)  # type: ignore[arg-type]


def test_decision_input_carries_every_coordinate() -> None:
    document = _assemble(at="2026-10-13T09:00:00Z")
    assert document == {
        "organisation_id": "org-1",
        "actor": "agent-identity-1",
        "agent_version_id": "agent-version-1",
        "tool_id": "tool-1",
        "environment": "prod",
        "risk_level": "low",
        "at": "2026-10-13T09:00:00Z",
        "policies": [],
    }


@pytest.mark.parametrize(
    "missing",
    [
        "organisation_id",
        "actor",
        "agent_version_id",
        "tool_id",
        "environment",
    ],
)
def test_a_missing_coordinate_is_rejected(missing: str) -> None:
    with pytest.raises(PolicyInputError) as excinfo:
        _assemble(**{missing: ""})
    assert excinfo.value.field == missing


def test_an_unknown_risk_level_is_rejected() -> None:
    with pytest.raises(PolicyInputError) as excinfo:
        _assemble(risk_level="enormous")
    assert excinfo.value.field == "risk_level"


def test_policies_are_normalised_to_the_documented_shape() -> None:
    document = _assemble(
        policies=[
            {
                "id": "p1",
                "version_id": "pv1",
                "effect": "allow",
                "tool_id": "tool-1",
                "environment": "prod",
                "agent_version_id": None,
                "valid_from": None,
                "valid_until": None,
                "unexpected_field": "must not leak into the decision input",
            }
        ]
    )
    policies = document["policies"]
    assert isinstance(policies, list)
    assert policies == [
        {
            "id": "p1",
            "version_id": "pv1",
            "effect": "allow",
            "agent_version_id": None,
            "tool_id": "tool-1",
            "environment": "prod",
            "valid_from": None,
            "valid_until": None,
        }
    ]


def test_a_policy_with_an_invalid_effect_is_rejected() -> None:
    with pytest.raises(PolicyInputError) as excinfo:
        _assemble(policies=[{"id": "p1", "effect": "maybe"}])
    assert excinfo.value.field == "effect"


@pytest.mark.parametrize("risk", ["high", "critical"])
def test_high_and_critical_risk_require_approval(risk: str) -> None:
    assert requires_approval(risk) is True


@pytest.mark.parametrize("risk", ["low", "medium"])
def test_lower_risk_does_not_require_approval(risk: str) -> None:
    assert requires_approval(risk) is False


def test_requires_approval_rejects_an_unknown_risk_level() -> None:
    with pytest.raises(PolicyInputError):
        requires_approval("enormous")


def test_escalation_takes_the_more_severe_level() -> None:
    assert escalate_risk("low", "critical") == "critical"
    assert escalate_risk("high", "medium") == "high"
    assert escalate_risk("medium", "medium") == "medium"


def test_escalation_without_an_observed_level_returns_the_declared_one() -> None:
    assert escalate_risk("high") == "high"


def test_escalation_rejects_an_unknown_level() -> None:
    with pytest.raises(PolicyInputError):
        escalate_risk("low", "enormous")
