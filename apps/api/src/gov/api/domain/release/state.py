"""Release lifecycle state machine.

Implements FR-030 to FR-032. The transitions are deliberately narrow:

- released -> canary -> promoted is the gradual rollout path;
- canary or promoted -> rolled_back is the recovery path, and it requires both a
  reason and a previous release to return to, because a rollback with nowhere to
  go is not a rollback;
- anything -> decommissioned is terminal, and requires a reason.

Every transition produces an immutable event, which is the in-memory counterpart
of the append-only release_event table (FR-031). A rollback that cannot complete
must leave the system in a known state, so the model never applies a partial
transition (FR-032).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

RELEASED = "released"
CANARY = "canary"
PROMOTED = "promoted"
ROLLED_BACK = "rolled_back"
DECOMMISSIONED = "decommissioned"

MIN_CANARY_PERCENT = 1
MAX_CANARY_PERCENT = 99


class ReleaseState(StrEnum):
    RELEASED = RELEASED
    CANARY = CANARY
    PROMOTED = PROMOTED
    ROLLED_BACK = ROLLED_BACK
    DECOMMISSIONED = DECOMMISSIONED


#: States in which the release is the one serving traffic for its Agent.
ACTIVE_STATES: frozenset[ReleaseState] = frozenset(
    {ReleaseState.RELEASED, ReleaseState.CANARY, ReleaseState.PROMOTED}
)


class ReleaseError(ValueError):
    """A release rule was violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReleaseError(
            "naive_datetime",
            f"{field_name} must be timezone-aware so state changes are comparable",
        )
    return value


def _require_reason(reason: str | None, action: str) -> str:
    if reason is None or not reason.strip():
        raise ReleaseError("reason_required", f"{action} must carry a reason")
    return reason


@dataclass(frozen=True, slots=True)
class ReleaseEvent:
    """An immutable record of one release state change."""

    from_state: str
    to_state: str
    actor_id: str
    occurred_at: datetime
    reason: str | None = None


@dataclass(slots=True)
class Release:
    """One Agent version's release state."""

    id: str
    organisation_id: str
    agent_id: str
    agent_version_id: str
    state: ReleaseState = ReleaseState.RELEASED
    canary_percent: int | None = None
    previous_release_id: str | None = None
    events: list[ReleaseEvent] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        """Whether this release is currently serving traffic for its Agent."""
        return self.state in ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state is ReleaseState.DECOMMISSIONED

    def _transition(
        self,
        *,
        to_state: ReleaseState,
        actor_id: str,
        at: datetime,
        reason: str | None = None,
    ) -> ReleaseEvent:
        _require_aware(at, "occurred_at")
        event = ReleaseEvent(
            from_state=self.state.value,
            to_state=to_state.value,
            actor_id=actor_id,
            occurred_at=at,
            reason=reason,
        )
        self.state = to_state
        self.events.append(event)
        return event

    def start_canary(
        self, *, percent: int, actor_id: str, at: datetime
    ) -> ReleaseEvent:
        """Begin a gradual rollout to a share of traffic.

        Raises:
            ReleaseError: when the release is not freshly released, or the share
                is outside the supported range.
        """
        if self.state is not ReleaseState.RELEASED:
            raise ReleaseError(
                "invalid_state",
                f"a canary can only start from released, not {self.state.value}",
            )
        if isinstance(percent, bool) or not isinstance(percent, int):
            raise ReleaseError("invalid_percent", "canary percent must be an integer")
        if not MIN_CANARY_PERCENT <= percent <= MAX_CANARY_PERCENT:
            raise ReleaseError(
                "invalid_percent",
                f"canary percent must be between {MIN_CANARY_PERCENT} and "
                f"{MAX_CANARY_PERCENT}; use promote for a full rollout",
            )
        self.canary_percent = percent
        return self._transition(
            to_state=ReleaseState.CANARY, actor_id=actor_id, at=at
        )

    def promote(self, *, actor_id: str, at: datetime) -> ReleaseEvent:
        """Promote a canary to the full rollout.

        Raises:
            ReleaseError: when the release is not a canary.
        """
        if self.state is not ReleaseState.CANARY:
            raise ReleaseError(
                "invalid_state",
                f"only a canary can be promoted, not {self.state.value}",
            )
        self.canary_percent = None
        return self._transition(
            to_state=ReleaseState.PROMOTED, actor_id=actor_id, at=at
        )

    def rollback(self, *, reason: str, actor_id: str, at: datetime) -> ReleaseEvent:
        """Return traffic to the previous release.

        Raises:
            ReleaseError: when there is no previous release to return to, when
                the current state cannot be rolled back, or when no reason is
                given.
        """
        if self.state not in (ReleaseState.CANARY, ReleaseState.PROMOTED):
            raise ReleaseError(
                "invalid_state",
                f"cannot roll back a release in state {self.state.value}",
            )
        if not self.previous_release_id:
            raise ReleaseError(
                "no_previous_release",
                "rollback requires a previous release to restore",
            )
        checked_reason = _require_reason(reason, "a rollback")
        self.canary_percent = None
        return self._transition(
            to_state=ReleaseState.ROLLED_BACK,
            actor_id=actor_id,
            at=at,
            reason=checked_reason,
        )

    def decommission(self, *, reason: str, actor_id: str, at: datetime) -> ReleaseEvent:
        """Retire the release permanently.

        Raises:
            ReleaseError: when the release is already decommissioned or no reason
                is given.
        """
        if self.state is ReleaseState.DECOMMISSIONED:
            raise ReleaseError(
                "invalid_state", "the release is already decommissioned"
            )
        checked_reason = _require_reason(reason, "a decommission")
        self.canary_percent = None
        return self._transition(
            to_state=ReleaseState.DECOMMISSIONED,
            actor_id=actor_id,
            at=at,
            reason=checked_reason,
        )
