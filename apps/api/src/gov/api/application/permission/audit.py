"""Permission-change records.

FR-021 and FR-022: every change to users, roles, permissions, assignments and
responsibility is recorded with the actor, the target, the change, the time and
the reason, and the record is permanent. The platform already has an append-only,
hash-chained trail that provides exactly that permanence (ADR-0007), so this
module writes to it rather than keeping a second history - two histories can
disagree, and then neither is evidence.

What this adds on top of a raw audit write is the part that is easy to get wrong
in three different places: one vocabulary of action names, so the trail can be
queried consistently, and the rule that some changes cannot be recorded without a
reason at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from gov.api.application.ports import AuditEntry, AuditPort, DomainEvent, EventPort

#: The action vocabulary. Stable strings, because the audit trail is queried by
#: them and a renamed action silently splits a history in two.
ROLE_CREATED = "role.create"
ROLE_UPDATED = "role.update"
ROLE_RETIRED = "role.retire"
PERMISSION_BOUND = "role.bind_permission"
PERMISSION_UNBOUND = "role.unbind_permission"
ASSIGNMENT_CREATED = "assignment.assign"
ASSIGNMENT_REVOKED = "assignment.revoke"
ASSIGNMENT_EXPIRED = "assignment.expire"
RESPONSIBILITY_ASSIGNED = "responsibility.assign"
RESPONSIBILITY_TRANSFERRED = "responsibility.transfer"
USER_CREATED = "user.create"
USER_UPDATED = "user.update"
USER_DISABLED = "user.disable"
USER_ENABLED = "user.enable"

#: Changes that must not be recorded without a reason, because the reason is the
#: only thing that later explains why access was removed or moved.
REQUIRES_REASON: frozenset[str] = frozenset(
    {
        ROLE_RETIRED,
        ASSIGNMENT_REVOKED,
        ASSIGNMENT_EXPIRED,
        RESPONSIBILITY_TRANSFERRED,
        PERMISSION_UNBOUND,
        USER_DISABLED,
    }
)

#: The audit event type these changes are filed under (FR-021).
PERMISSION_CHANGE_EVENT = "identity_change"


class PermissionChangeError(ValueError):
    """A change cannot be recorded as stated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PermissionChange:
    """One change to record."""

    organisation_id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionChangeRecorder:
    """Writes permission changes to the audit trail and the event stream."""

    audit: AuditPort
    events: EventPort | None = None
    clock: Callable[[], datetime] | None = None

    def record(self, change: PermissionChange) -> AuditEntry:
        """Record a change.

        Raises:
            PermissionChangeError: when the action requires a reason and none was
                given. Refusing here is what keeps the trail answerable: a
                revocation without a reason is a hole a reviewer cannot fill in
                afterwards.
        """
        if change.action in REQUIRES_REASON and not (change.reason or "").strip():
            raise PermissionChangeError(
                "reason_required",
                f"a reason is required to record {change.action}",
            )

        entry = AuditEntry(
            organisation_id=change.organisation_id,
            actor=change.actor,
            action=change.action,
            target_type=change.target_type,
            target_id=change.target_id,
            outcome="success",
            reason=change.reason,
            detail=dict(change.detail),
            occurred_at=self.clock() if self.clock is not None else None,
        )
        # Not wrapped in a try: a failing audit write must propagate so the
        # caller's transaction rolls back. A change that happened without its
        # record is worse than a change that did not happen.
        self.audit.record(entry)

        if self.events is not None:
            self.events.publish(
                DomainEvent(
                    event_type=PERMISSION_CHANGE_EVENT,
                    organisation_id=change.organisation_id,
                    aggregate_type=change.target_type,
                    aggregate_id=change.target_id,
                    payload={
                        "action": change.action,
                        "actor": change.actor,
                        **dict(change.detail),
                    },
                )
            )
        return entry
