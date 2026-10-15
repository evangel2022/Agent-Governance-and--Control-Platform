"""Reading the audit trail (FR-023, US5).

Two questions this answers, and they are different questions:

* **Search** - "show me everything of this kind", narrowed by target, actor,
  outcome and time.
* **Replay** - "what did this role grant at that moment?". The answer comes from
  replaying the recorded changes up to that moment, never from current state.
  Current state tells you what is true now; only the trail tells you what was
  true then, which is the question an audit is asked to answer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from gov.api.application.permission.audit import PERMISSION_BOUND, PERMISSION_UNBOUND
from gov.api.application.ports import AuditEntry, UnitOfWork


@dataclass(frozen=True, slots=True)
class AuditFilter:
    """The narrowing criteria a search accepts."""

    target_type: str | None = None
    target_id: str | None = None
    actor: str | None = None
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 200


@dataclass(frozen=True, slots=True)
class PermissionState:
    """What a role granted at a moment, and the evidence for it."""

    role_id: str
    permissions: frozenset[str]
    sources: tuple[AuditEntry, ...] = field(default=())


class AuditQueryService:
    """Reads and replays the audit trail."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    def search(self, *, organisation_id: str, criteria: AuditFilter) -> Sequence[AuditEntry]:
        """Return the entries matching a filter, oldest first."""
        with self._uow() as uow:
            found = uow.audit.search(
                organisation_id=organisation_id,
                target_type=criteria.target_type,
                target_id=criteria.target_id,
                actor=criteria.actor,
                outcome=criteria.outcome,
                since=criteria.since,
                until=criteria.until,
            )
        ordered = sorted(found, key=lambda entry: entry.occurred_at or datetime.min)
        return ordered[: criteria.limit]

    def reconstruct(
        self, *, organisation_id: str, target_type: str, target_id: str
    ) -> Sequence[AuditEntry]:
        """Return every recorded change to one target, oldest first."""
        with self._uow() as uow:
            entries = uow.audit.history_for(
                organisation_id=organisation_id,
                target_type=target_type,
                target_id=target_id,
            )
        return tuple(sorted(entries, key=lambda entry: entry.occurred_at or datetime.min))

    def permissions_at(
        self,
        *,
        organisation_id: str,
        role_id: str,
        at: datetime,
    ) -> PermissionState:
        """Replay a role's bindings up to a moment.

        The result is derived from the trail rather than read from the current
        binding table, so it answers "what was true then" even after the bindings
        have changed.
        """
        entries = self.reconstruct(
            organisation_id=organisation_id, target_type="role", target_id=role_id
        )
        granted: set[str] = set()
        evidence: list[AuditEntry] = []
        for entry in entries:
            occurred = entry.occurred_at
            if occurred is not None and occurred > at:
                break
            permission = entry.detail.get("permission_name")
            if not isinstance(permission, str):
                continue
            if entry.action == PERMISSION_BOUND:
                granted.add(permission)
            elif entry.action == PERMISSION_UNBOUND:
                granted.discard(permission)
            else:
                continue
            evidence.append(entry)
        return PermissionState(
            role_id=role_id, permissions=frozenset(granted), sources=tuple(evidence)
        )
