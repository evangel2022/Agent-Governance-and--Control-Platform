"""Responsibility use cases (FR-013, FR-014, FR-015).

Accountability is `agent.owner_user_id`. A transfer updates that column and
writes its reason to the audit trail in the same transaction, so the history is
derived rather than stored twice.

The decision cache is invalidated on a transfer: a developer's authority over an
Agent follows accountability, so moving accountability changes what somebody may
do, and it must change at the next verification rather than at the end of a TTL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gov.api.application.permission.audit import (
    RESPONSIBILITY_ASSIGNED,
    RESPONSIBILITY_TRANSFERRED,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.ports import (
    AgentRecord,
    NotFoundError,
    UnitOfWork,
    ValidationFailure,
)
from gov.api.domain.permission.responsibility import validate_transfer
from gov.api.domain.permission.rules import PermissionRuleError


@dataclass(frozen=True, slots=True)
class TransferHistoryEntry:
    """One recorded change of accountability."""

    action: str
    actor: str
    accountable_user_id: str | None
    occurred_at: datetime | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ResponsibilityView:
    """Who is accountable for an Agent, and how that came to be."""

    agent_id: str
    accountable_user_id: str
    assigned_at: datetime | None
    history: tuple[TransferHistoryEntry, ...]


class ResponsibilityService:
    """Accountability for Agent resources."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime],
        cache: EffectivePermissionCache | None = None,
    ) -> None:
        self._uow = uow_factory
        self._clock = clock
        self._cache = cache

    def get(self, *, organisation_id: str, agent_id: str) -> ResponsibilityView:
        """Return the accountable person and the transfer history.

        The history is read from the audit trail rather than from a second table,
        so it cannot disagree with the record of what actually happened.
        """
        with self._uow() as uow:
            agent = self._require_agent(uow, organisation_id, agent_id)
            entries = uow.audit.history_for(
                organisation_id=organisation_id,
                target_type="agent",
                target_id=agent_id,
            )
            return ResponsibilityView(
                agent_id=agent.id,
                accountable_user_id=agent.owner_user_id,
                assigned_at=agent.created_at,
                history=tuple(
                    TransferHistoryEntry(
                        action=entry.action,
                        actor=entry.actor,
                        accountable_user_id=entry.detail.get("accountable_user_id"),
                        occurred_at=entry.occurred_at,
                        reason=entry.reason,
                    )
                    for entry in entries
                    if entry.action
                    in (RESPONSIBILITY_ASSIGNED, RESPONSIBILITY_TRANSFERRED)
                ),
            )

    def transfer(
        self,
        *,
        organisation_id: str,
        agent_id: str,
        accountable_user_id: str,
        reason: str,
        actor: str,
    ) -> ResponsibilityView:
        """Move accountability for an Agent to another person.

        Raises:
            NotFoundError: when the Agent, or the new holder, is not visible here.
            ValidationFailure: when no reason is given, or the transfer would
                change nothing.
        """
        with self._uow() as uow:
            agent = self._require_agent(uow, organisation_id, agent_id)
            incoming = self._require_user(uow, organisation_id, accountable_user_id)

            try:
                validate_transfer(
                    current_owner_user_id=agent.owner_user_id,
                    new_owner_user_id=incoming.id,
                    reason=reason,
                )
            except PermissionRuleError as error:
                raise ValidationFailure(
                    str(error), errors=[{"field": "reason", "message": error.message}]
                ) from error

            previous = agent.owner_user_id
            agent.owner_user_id = incoming.id
            agent.updated_at = self._clock()
            uow.agents.update_agent(agent)

            PermissionChangeRecorder(
                audit=uow.audit, events=uow.events, clock=self._clock
            ).record(
                PermissionChange(
                    organisation_id=organisation_id,
                    actor=actor,
                    action=RESPONSIBILITY_TRANSFERRED,
                    target_type="agent",
                    target_id=agent.id,
                    reason=reason,
                    detail={
                        "accountable_user_id": incoming.id,
                        "previous_accountable_user_id": previous,
                    },
                )
            )
            if self._cache is not None:
                self._cache.bump(organisation_id)

            return self.get(organisation_id=organisation_id, agent_id=agent.id)

    # --------------------------------------------------------------- helpers

    def _require_agent(
        self, uow: UnitOfWork, organisation_id: str, agent_id: str
    ) -> AgentRecord:
        try:
            return uow.agents.get_agent(organisation_id, agent_id)
        except LookupError as exc:
            raise NotFoundError(f"agent {agent_id!r} does not exist") from exc

    def _require_user(self, uow: UnitOfWork, organisation_id: str, user_id: str):  # type: ignore[no-untyped-def]
        try:
            user = uow.users.get_user(organisation_id, user_id)
        except LookupError as exc:
            raise NotFoundError(f"user {user_id!r} does not exist") from exc
        if user.status != "active":
            raise ValidationFailure(
                "accountability must rest with an active user",
                errors=[{"field": "accountable_user_id", "message": "user is disabled"}],
            )
        return user
