"""Policy decision-input assembly and risk classification.

ADR-0005 makes OPA the single source of truth for allow/deny resolution, so this
module deliberately does not re-implement that resolution. Implementing deny by
default and deny-wins here as well would create a second, silently divergent
authority for the platform's most security-critical decision.

What this module owns is:

1. assembling the exact input document OPA consumes, so a decision is
   reproducible from the audit trail (FR-014, FR-026); and
2. the risk rules of FR-016, which govern how a decision may be acted upon
   rather than what the decision is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from gov.api.domain.registry.entities import RISK_LEVELS, DomainValidationError

#: Risk levels that can never be authorised by policy alone (FR-016).
APPROVAL_REQUIRED_RISKS: frozenset[str] = frozenset({"high", "critical"})


class PolicyInputError(DomainValidationError):
    """The decision input could not be assembled."""


def _require(value: Any, field_name: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise PolicyInputError(field_name, "is required to evaluate policy")
    return value


def _require_risk(value: Any, field_name: str = "risk_level") -> str:
    if value not in RISK_LEVELS:
        raise PolicyInputError(field_name, f"must be one of {', '.join(RISK_LEVELS)}")
    return str(value)


def requires_approval(risk_level: str) -> bool:
    """Return whether a risk level requires a recorded human approval (FR-016)."""
    return _require_risk(risk_level) in APPROVAL_REQUIRED_RISKS


def escalate_risk(declared: str, observed: str | None = None) -> str:
    """Return the more severe of the declared and observed risk levels.

    Used when a Tool's risk level rises while a request is in flight: the request
    is re-evaluated under the higher classification rather than completing under
    the old one (edge case "risk level raised while a request is pending").
    """
    declared_checked = _require_risk(declared, "declared_risk_level")
    if observed is None:
        return declared_checked
    observed_checked = _require_risk(observed, "observed_risk_level")
    return max(declared_checked, observed_checked, key=RISK_LEVELS.index)


def assemble_decision_input(
    *,
    organisation_id: str,
    actor: str,
    agent_version_id: str,
    tool_id: str,
    environment: str,
    risk_level: str,
    policies: Sequence[Mapping[str, Any]],
    at: str | None = None,
) -> dict[str, Any]:
    """Build the document OPA evaluates.

    The shape matches deploy/policy/policy.rego. Keeping assembly here and
    resolution there means a decision can be replayed from the audit trail by
    feeding the same document back to OPA.

    Raises:
        PolicyInputError: when a required coordinate is missing or the risk level
            is not one the platform recognises.
    """
    return {
        "organisation_id": _require(organisation_id, "organisation_id"),
        "actor": _require(actor, "actor"),
        "agent_version_id": _require(agent_version_id, "agent_version_id"),
        "tool_id": _require(tool_id, "tool_id"),
        "environment": _require(environment, "environment"),
        "risk_level": _require_risk(risk_level),
        "at": at,
        "policies": _normalise_policies(policies),
    }


def _normalise_policies(policies: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalise candidate policies into the document OPA expects.

    Only the fields the policy bundle reads are carried through, so an unexpected
    attribute cannot influence a decision by accident.
    """
    normalised: list[dict[str, Any]] = []
    for policy in policies:
        effect = policy.get("effect")
        if effect not in ("allow", "deny"):
            raise PolicyInputError(
                "effect",
                f"policy {policy.get('id')!r} has an invalid effect {effect!r}",
            )
        normalised.append(
            {
                "id": policy.get("id"),
                "version_id": policy.get("version_id"),
                "effect": effect,
                "agent_version_id": policy.get("agent_version_id"),
                "tool_id": policy.get("tool_id"),
                "environment": policy.get("environment"),
                "valid_from": policy.get("valid_from"),
                "valid_until": policy.get("valid_until"),
            }
        )
    return normalised
