"""Registry entities and their validation rules.

Implements FR-005 to FR-010. Registration must reject incomplete or duplicate
entries at the boundary, so validation lives on the entity rather than in the
router: an invalid entity cannot be constructed at all, which is what makes
"no partial record" (US1 scenario 4) true rather than merely intended.

Entity identity, uniqueness and lifecycle transitions are enforced by the
database schema and the application layer; this module owns the field-level
rules that are independent of storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from gov.api.domain.classification import validate_classification

NAME_MAX = 200
DESCRIPTION_MAX = 4000
RISK_BASIS_MAX = 2000

#: Risk levels, least to most severe.
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")

#: Actions a Tool may be permitted to perform (FR-007).
ACTIONS: tuple[str, ...] = ("read", "write", "execute", "approve", "delete")

AGENT_STATUSES: tuple[str, ...] = ("draft", "active", "deprecated", "retired")
VERSION_STATUSES: tuple[str, ...] = (
    "draft",
    "in_review",
    "released",
    "deprecated",
    "retired",
)
TOOL_STATUSES: tuple[str, ...] = ("draft", "active", "deprecated", "retired")

# Semantic versioning: MAJOR.MINOR.PATCH, optional prerelease, optional build
# metadata. A fourth numeric segment (1.0.0.0) is not a version and is rejected.
_SEMVER = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?(?:\+[A-Za-z0-9.]+)?$"
)


class DomainValidationError(ValueError):
    """A field-level validation failure, safe to surface to a client."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(f"{field_name}: {message}")
        self.field = field_name
        self.message = message


def _require_text(value: Any, field_name: str, *, max_length: int) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise DomainValidationError(field_name, "is required")
    if len(value) > max_length:
        raise DomainValidationError(
            field_name, f"must be at most {max_length} characters"
        )
    return value


def _optional_text(value: Any, field_name: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name, max_length=max_length)


def _require_choice(value: Any, field_name: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise DomainValidationError(
            field_name, f"must be one of {', '.join(choices)}"
        )
    return str(value)


def validate_version(version: str) -> str:
    """Validate a semantic-version-shaped Agent version identifier."""
    if not isinstance(version, str) or not _SEMVER.match(version):
        raise DomainValidationError("version", "must look like 1.2.3 or 1.2.3-rc1")
    return version


def derive_sandbox_class(risk_level: str) -> str:
    """Return the isolation class a Tool of this risk level requires (ADR-0006)."""
    checked = _require_choice(risk_level, "risk_level", RISK_LEVELS)
    return "dedicated" if checked in ("high", "critical") else "shared"


@dataclass(frozen=True)
class ToolPermission:
    """One declared permission of a Tool (FR-007)."""

    resource_type: str
    action: str
    data_class: str
    constraint: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.resource_type, "resource_type", max_length=NAME_MAX)
        _require_choice(self.action, "action", ACTIONS)
        validate_classification(self.data_class)


@dataclass(frozen=True)
class Tool:
    """An invocable capability with declared permissions and a risk level."""

    name: str
    risk_level: str
    risk_basis: str
    adapter_ref: str
    permissions: tuple[ToolPermission, ...]
    description: str | None = None
    status: str = "draft"

    def __post_init__(self) -> None:
        _require_text(self.name, "name", max_length=NAME_MAX)
        _require_choice(self.risk_level, "risk_level", RISK_LEVELS)
        _require_text(self.risk_basis, "risk_basis", max_length=RISK_BASIS_MAX)
        _require_text(self.adapter_ref, "adapter_ref", max_length=NAME_MAX)
        _optional_text(self.description, "description", max_length=DESCRIPTION_MAX)
        _require_choice(self.status, "status", TOOL_STATUSES)
        if not self.permissions:
            raise DomainValidationError(
                "permissions", "at least one permission must be declared"
            )

    @property
    def requires_sandbox_class(self) -> str:
        return derive_sandbox_class(self.risk_level)

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("high", "critical")


@dataclass(frozen=True)
class Agent:
    """A governed automated actor."""

    name: str
    owner_user_id: str
    description: str | None = None
    status: str = "draft"

    def __post_init__(self) -> None:
        _require_text(self.name, "name", max_length=NAME_MAX)
        _require_text(self.owner_user_id, "owner_user_id", max_length=NAME_MAX)
        _optional_text(self.description, "description", max_length=DESCRIPTION_MAX)
        _require_choice(self.status, "status", AGENT_STATUSES)


@dataclass(frozen=True)
class AgentVersion:
    """A version of an Agent.

    At most one version per Agent may be `released`; that invariant is enforced
    by a partial unique index and checked in the application layer, because it
    spans rows and cannot be validated from a single instance.
    """

    agent_id: str
    version: str
    owner_user_id: str
    status: str = "draft"
    model_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.agent_id, "agent_id", max_length=NAME_MAX)
        validate_version(self.version)
        _require_text(self.owner_user_id, "owner_user_id", max_length=NAME_MAX)
        _require_choice(self.status, "status", VERSION_STATUSES)
