"""Assembly of the authorization decision input.

The control plane resolves the facts - who is asking, what they hold, and what
the request is about - and the decision component decides. This module owns the
first half, and deliberately not the second: assembling the input here keeps the
interface layer free of adapter details while leaving the decision to the one
authority ADR-0011 names.

The document is self-contained and carries its schema version, so a past decision
can be replayed by feeding the same document back to the engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_authorization_input(
    *,
    organisation_id: str,
    user_id: str,
    permission: str,
    permissions: Sequence[str],
    roles: Sequence[Mapping[str, Any]] = (),
    resource: Mapping[str, Any] | None = None,
    requires_resource_accountability: bool = False,
    requested_at: str | None = None,
    context: Mapping[str, Any] | None = None,
    schema_version: int = 1,
) -> dict[str, Any]:
    """Assemble the document the decision component evaluates."""
    return {
        "schema_version": schema_version,
        "organisation_id": organisation_id,
        "user_id": user_id,
        "permission": permission,
        "requested_at": requested_at,
        "permissions": sorted(permissions),
        "roles": [dict(role) for role in roles],
        "requires_resource_accountability": requires_resource_accountability,
        "resource": dict(resource) if resource is not None else None,
        "context": dict(context or {}),
    }
