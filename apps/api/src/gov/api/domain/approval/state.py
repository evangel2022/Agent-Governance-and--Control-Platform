"""The approval state machine for high-risk operations.

Implements FR-017 to FR-022. The rules that matter here are the ones an attacker
would otherwise exploit:

- only a pending request can be decided, so a decided request is never reopened;
- a decision must carry a reason, so every outcome is explicable (FR-039);
- a requester cannot approve their own request unless policy explicitly allows it
  (FR-022);
- one approver cannot satisfy a dual-control requirement twice;
- the request closes only when the tally of distinct approving users reaches the
  configured requirement.

Decisions are frozen value objects, the in-memory counterpart of the append-only
approval_decision table (FR-019).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

APPROVE = "approve"
REJECT = "reject"
DECISIONS: tuple[str, ...] = (APPROVE, REJECT)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalError(ValueError):
    """An approval rule was violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApprovalError(
            "naive_datetime",
            f"{field_name} must be timezone-aware so decisions are comparable",
        )
    return value


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """An immutable record of one approver's decision."""

    approver_user_id: str
    decision: str
    reason: str
    decided_at: datetime


@dataclass(slots=True)
class ApprovalRequest:
    """A request for human authorisation of one high-risk invocation."""

    id: str
    organisation_id: str
    invocation_id: str
    requested_by: str
    expires_at: datetime
    required_approvals: int = 1
    allow_self_approval: bool = False
    status: ApprovalStatus = ApprovalStatus.PENDING
    decisions: list[ApprovalDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.required_approvals < 1:
            raise ApprovalError(
                "invalid_required_approvals",
                "required_approvals must be at least 1",
            )
        _require_aware(self.expires_at, "expires_at")

    @property
    def approvers(self) -> frozenset[str]:
        """The distinct users who have approved so far."""
        return frozenset(
            decision.approver_user_id
            for decision in self.decisions
            if decision.decision == APPROVE
        )

    @property
    def is_pending(self) -> bool:
        return self.status is ApprovalStatus.PENDING

    def decide(
        self,
        *,
        approver_user_id: str,
        decision: str,
        reason: str,
        at: datetime,
    ) -> ApprovalDecision:
        """Record a decision, advancing the request when the tally is met.

        Raises:
            ApprovalError: for a non-pending request, an invalid decision, a
                blank reason, self-approval when it is not permitted, or a
                second decision from the same approver.
        """
        _require_aware(at, "decided_at")

        if self.status is not ApprovalStatus.PENDING:
            raise ApprovalError(
                "not_pending",
                f"request is {self.status.value} and can no longer be decided",
            )
        if decision not in DECISIONS:
            raise ApprovalError(
                "invalid_decision", f"decision must be one of {', '.join(DECISIONS)}"
            )
        if not reason or not reason.strip():
            raise ApprovalError("reason_required", "a decision must carry a reason")
        if approver_user_id == self.requested_by and not self.allow_self_approval:
            raise ApprovalError(
                "self_approval_forbidden",
                "the requester may not approve their own request",
            )
        if any(
            existing.approver_user_id == approver_user_id for existing in self.decisions
        ):
            raise ApprovalError(
                "duplicate_approver",
                "this approver has already decided the request",
            )

        recorded = ApprovalDecision(
            approver_user_id=approver_user_id,
            decision=decision,
            reason=reason,
            decided_at=at,
        )
        self.decisions.append(recorded)

        if decision == REJECT:
            self.status = ApprovalStatus.REJECTED
        elif len(self.approvers) >= self.required_approvals:
            self.status = ApprovalStatus.APPROVED

        return recorded

    def expire(self, *, at: datetime) -> bool:
        """Expire the request if it is still pending and past its window.

        Returns True when the request transitioned to expired.
        """
        _require_aware(at, "at")
        if self.status is not ApprovalStatus.PENDING or at <= self.expires_at:
            return False
        self.status = ApprovalStatus.EXPIRED
        return True

    def cancel(self) -> None:
        """Cancel a pending request, for example when its invocation is withdrawn."""
        if self.status is not ApprovalStatus.PENDING:
            raise ApprovalError(
                "not_pending",
                f"request is {self.status.value} and can no longer be cancelled",
            )
        self.status = ApprovalStatus.CANCELLED
