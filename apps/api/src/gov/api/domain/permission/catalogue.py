"""The permission catalogue.

FR-007 requires every permission to be identifiable by a stable name and a plain
description of the action it authorises. The catalogue is that description, and it
is **platform-wide reference data**: it lists the actions the platform recognises
and contains no organisation's information, so it carries no tenant column.

The catalogue deliberately describes the *existing* permission names from
`gov.api.domain.identity.permissions` rather than inventing a parallel vocabulary.
Two names for one action is how a permission system starts disagreeing with
itself, and a test asserts the two sets are identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Lowercase, dot-separated, at least one dot: `resource.action` or
#: `resource.something.action`.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")


class PermissionNameError(ValueError):
    """A permission definition is malformed."""


class UnknownPermissionError(LookupError):
    """A name is not in the catalogue.

    Raised rather than defaulting, because FR-008 requires an unrecognised name
    to grant nothing - and silently accepting it would grant whatever a caller
    guessed.
    """


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    """One authorisable action."""

    name: str
    description: str
    is_builtin: bool = False

    def __post_init__(self) -> None:
        if not NAME_PATTERN.match(self.name):
            raise PermissionNameError(
                f"permission name {self.name!r} must look like resource.action"
            )
        if not self.description.strip():
            raise PermissionNameError(
                f"permission {self.name!r} needs a description"
            )

    @property
    def resource(self) -> str:
        """The family the action belongs to, e.g. `registry`."""
        return self.name.split(".", 1)[0]

    @property
    def action(self) -> str:
        """The verb, e.g. `read` or `retire`."""
        return self.name.rsplit(".", 1)[-1]


#: Every action the platform authorises. Built-in entries are the ones the
#: platform's own roles depend on; the flag exists so a future custom permission
#: can be distinguished from a baseline one.
CATALOGUE: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(
        "registry.read", "Read Agents, Agent versions, Tools and Models.", True
    ),
    PermissionDefinition("registry.write", "Register and update registry entries.", True),
    PermissionDefinition("registry.retire", "Retire a registry entry.", True),
    PermissionDefinition(
        "registry.write_any",
        "Modify any Agent, regardless of who is accountable for it.",
        True,
    ),
    PermissionDefinition("policy.read", "Read the policy definitions in force.", True),
    PermissionDefinition("policy.write", "Draft a policy.", True),
    PermissionDefinition("policy.publish", "Publish an immutable policy version.", True),
    PermissionDefinition("approval.read", "Read approval requests and their evidence.", True),
    PermissionDefinition("approval.decide", "Approve or reject a high-risk request.", True),
    PermissionDefinition("audit.read", "Search the append-only audit trail.", True),
    PermissionDefinition("audit.export", "Export a set of audit results.", True),
    PermissionDefinition("release.read", "Read the release state of Agent versions.", True),
    PermissionDefinition("release.write", "Release, promote, roll back or decommission.", True),
    PermissionDefinition("evaluation.read", "Read evaluation tasks, datasets and reports.", True),
    PermissionDefinition("evaluation.write", "Create and run an evaluation.", True),
    PermissionDefinition(
        "dashboard.read", "Read operational status and governance metrics.", True
    ),
    PermissionDefinition("identity.manage", "Administer users, roles and assignments.", True),
    PermissionDefinition("risk.raise", "Raise a risk event.", True),
)

BY_NAME: dict[str, PermissionDefinition] = {item.name: item for item in CATALOGUE}

if len(BY_NAME) != len(CATALOGUE):  # pragma: no cover - guards a typo at import
    duplicates = sorted(
        name for name in BY_NAME if sum(p.name == name for p in CATALOGUE) > 1
    )
    raise PermissionNameError(f"duplicate permission names: {duplicates}")


def get(name: str) -> PermissionDefinition:
    """Return the definition for a name.

    Raises:
        UnknownPermissionError: when the name is not catalogued.
    """
    try:
        return BY_NAME[name]
    except KeyError as exc:
        raise UnknownPermissionError(f"unknown permission: {name!r}") from exc


def by_resource(resource: str) -> tuple[PermissionDefinition, ...]:
    """Return every catalogued action in a resource family."""
    return tuple(item for item in CATALOGUE if item.resource == resource)


def resources() -> tuple[str, ...]:
    """Return the resource families, in catalogue order."""
    seen: list[str] = []
    for item in CATALOGUE:
        if item.resource not in seen:
            seen.append(item.resource)
    return tuple(seen)
