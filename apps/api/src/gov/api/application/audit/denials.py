"""Recording refused attempts (FR-024, SC-008).

A refusal that leaves no trace answers only half the question an auditor asks.
"The auditor may not write" is a claim about the system; "the auditor tried to
write, was refused, and here is the refusal" is evidence. This module is the
second half.

It writes to the same append-only trail as every other change (ADR-0007). A
refusal is not a permission change, so it lives outside the mutation's
transaction by nature - there was no mutation to join - and that is why it is a
small, separate writer rather than part of the use cases.

Only refusals that carry an organisation and an actor are recorded. An
unauthenticated request has neither, and inventing an organisation for it would
put a fabricated tenant in the trail, which the isolation rules forbid; that
case belongs to the edge, not to a tenant-scoped trail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gov.api.application.ports import AuditEntry, UnitOfWork

#: The outcome recorded for every refusal. Not "success": the audit trail has to
#: let a reader separate what happened from what was prevented.
DENIED_OUTCOME = "denied"

#: Actions, in the same vocabulary style as the permission-change actions, so the
#: trail can be searched for refusals as one thing.
ACCESS_DENIED = "access.denied"
ACCESS_INDETERMINATE = "access.indeterminate"

#: The statuses that represent a refusal rather than a client mistake. A 404 or a
#: 422 is not a refusal of authority and is deliberately not recorded here.
REFUSAL_STATUSES: frozenset[int] = frozenset({403, 503})

_ACTION_FOR_STATUS: dict[int, str] = {
    403: ACCESS_DENIED,
    503: ACCESS_INDETERMINATE,
}


@dataclass
class DenialRecorder:
    """Writes refusals to the audit trail, each in its own transaction."""

    uow_factory: Callable[[], UnitOfWork]
    clock: Callable[[], datetime] | None = None

    def record(
        self,
        *,
        organisation_id: str,
        actor: str,
        status: int,
        method: str,
        path: str,
        reason: str,
    ) -> None:
        """Append one refusal.

        The caller decides whether the refusal is recordable; this only writes.
        A failure to write is the caller's to swallow, because the refusal has
        already happened and the safe outcome is already in hand - losing the
        record must not turn a refusal into a success.
        """
        action = _ACTION_FOR_STATUS.get(status, ACCESS_DENIED)
        entry = AuditEntry(
            organisation_id=organisation_id,
            actor=actor,
            action=action,
            target_type="request",
            target_id=f"{method.upper()} {path}",
            outcome=DENIED_OUTCOME,
            reason=reason,
            detail={"method": method.upper(), "path": path, "status": status},
            occurred_at=self.clock() if self.clock is not None else None,
        )
        with self.uow_factory() as uow:
            uow.audit.record(entry)
