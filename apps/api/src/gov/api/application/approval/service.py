"""Approval use cases: raise, list, decide and expire high-risk approvals.

Implements FR-017 to FR-022 (US3). The state machine lives in the domain
(`gov.api.domain.approval`); this layer orchestrates it, records the outcome and
translates domain refusals into the transport-neutral errors the interface layer
maps onto problem responses.

Two mappings decide what a caller sees, so they are worth stating:

- a requester deciding their own request is a **forbidden** action (403), not a
  validation error: the caller is authenticated and the action itself is
  disallowed;
- deciding a request that is already settled or expired is a **conflict** (409):
  the request is well formed, but the server's state refuses it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from gov.api.application.ports import (
    ApplicationError,
    AuditEntry,
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    UnitOfWork,
    ValidationFailure,
)
from gov.api.domain.approval.state import (
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)

APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
APPROVAL_EXPIRED = "approval.expired"

#: Domain error codes that are conflicts rather than malformed requests.
_CONFLICT_CODES = frozenset(
    {"not_pending", "duplicate_approver", "invalid_required_approvals"}
)


def _translate(error: ApprovalError) -> ApplicationError:
    """Map a domain refusal onto a transport-neutral application error."""
    if error.code == "self_approval_forbidden":
        return ForbiddenError(str(error))
    if error.code in _CONFLICT_CODES:
        return ConflictError(str(error))
    return ValidationFailure(str(error))


class ApprovalService:
    """Approval use cases over a unit of work."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        new_id: Callable[[], str],
    ) -> None:
        self._uow = uow_factory
        self._new_id = new_id
        #: Evidence is review material rather than a rule input, so it is held
        #: beside the domain aggregate instead of inside it.
        self._evidence: dict[str, dict[str, Any]] = {}

    def raise_request(
        self,
        *,
        organisation_id: str,
        invocation_id: str,
        requested_by: str,
        expires_at: datetime,
        actor: str,
        required_approvals: int = 1,
        allow_self_approval: bool = False,
        evidence: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ApprovalRequest:
        """Raise an approval request for one high-risk invocation (FR-017).

        An invocation has at most one approval request, so a retry carrying the
        same invocation returns the existing request rather than raising a second
        one (FR-022, quickstart V8).
        """
        with self._uow() as uow:
            existing = self._find_by_invocation(uow, organisation_id, invocation_id)
            if existing is not None:
                return existing

            request = ApprovalRequest(
                id=self._new_id(),
                organisation_id=organisation_id,
                invocation_id=invocation_id,
                requested_by=requested_by,
                expires_at=expires_at,
                required_approvals=required_approvals,
                allow_self_approval=allow_self_approval,
            )
            self._evidence[request.id] = dict(evidence or {})
            uow.approvals.add(request)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="request",
                request=request,
                event_type=APPROVAL_REQUESTED,
                detail={
                    "invocation_id": invocation_id,
                    "required_approvals": required_approvals,
                    "expires_at": expires_at.isoformat(),
                    "idempotency_key": idempotency_key,
                },
            )
        return request

    def list_by_status(
        self, *, organisation_id: str, status: ApprovalStatus = ApprovalStatus.PENDING
    ) -> Sequence[ApprovalRequest]:
        """Return requests in a given state; the default is the approver queue."""
        with self._uow() as uow:
            return list(uow.approvals.list_by_status(organisation_id, status))

    def get(self, *, organisation_id: str, request_id: str) -> ApprovalRequest:
        """Return one request, for the evidence an approver reviews."""
        with self._uow() as uow:
            return self._require(uow, organisation_id, request_id)

    def evidence_for(self, *, request_id: str) -> dict[str, Any]:
        """Return the evidence recorded when the request was raised."""
        return dict(self._evidence.get(request_id, {}))

    def decide(
        self,
        *,
        organisation_id: str,
        request_id: str,
        approver_user_id: str,
        decision: str,
        reason: str,
        at: datetime,
        idempotency_key: str | None = None,
    ) -> ApprovalRequest:
        """Record an approver's decision (FR-018, FR-019, FR-022).

        Raises:
            NotFoundError: the request does not exist in this organisation.
            ForbiddenError: the requester tried to approve their own request.
            ConflictError: the request is settled, expired, or already decided by
                this approver.
            ValidationFailure: a blank reason or an unknown decision.
        """
        with self._uow() as uow:
            request = self._require(uow, organisation_id, request_id)
            try:
                request.decide(
                    approver_user_id=approver_user_id,
                    decision=decision,
                    reason=reason,
                    at=at,
                )
            except ApprovalError as error:
                raise _translate(error) from error

            uow.approvals.save(request)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=approver_user_id,
                action=decision,
                request=request,
                event_type=APPROVAL_DECIDED,
                reason=reason,
                detail={
                    "decision": decision,
                    "approver_user_id": approver_user_id,
                    "status": request.status.value,
                    "idempotency_key": idempotency_key,
                },
            )
        return request

    def expire_due(self, *, organisation_id: str, at: datetime) -> int:
        """Expire every pending request past its window (FR-020).

        Returns how many requests were expired. The expiry worker (T066) drives
        this, and it is tested here so the rule is verified with the rest of the
        lifecycle rather than only once the scheduler exists.
        """
        expired = 0
        with self._uow() as uow:
            for request in list(uow.approvals.list_by_status(organisation_id)):
                if not request.expire(at=at):
                    continue
                uow.approvals.save(request)
                expired += 1
                self._emit(
                    uow,
                    organisation_id=organisation_id,
                    actor=request.requested_by,
                    action="expire",
                    request=request,
                    event_type=APPROVAL_EXPIRED,
                    outcome="denied",
                    reason="the approval window elapsed without a decision",
                    detail={"expires_at": request.expires_at.isoformat()},
                )
        return expired

    # ----------------------------------------------------------------- helpers

    def _require(
        self, uow: UnitOfWork, organisation_id: str, request_id: str
    ) -> ApprovalRequest:
        try:
            return uow.approvals.get(organisation_id, request_id)
        except LookupError as exc:
            raise NotFoundError(
                f"approval request {request_id!r} does not exist"
            ) from exc

    def _find_by_invocation(
        self, uow: UnitOfWork, organisation_id: str, invocation_id: str
    ) -> ApprovalRequest | None:
        """Return any existing request for an invocation, in any state.

        Checking every state matters: a retry after a decision must still find the
        original request rather than raising a second one.
        """
        for status in ApprovalStatus:
            for request in uow.approvals.list_by_status(organisation_id, status):
                if request.invocation_id == invocation_id:
                    return request
        return None

    def _emit(
        self,
        uow: UnitOfWork,
        *,
        organisation_id: str,
        actor: str,
        action: str,
        request: ApprovalRequest,
        event_type: str,
        detail: dict[str, Any],
        outcome: str = "success",
        reason: str | None = None,
    ) -> None:
        payload = dict(detail)
        payload["approval_request_id"] = request.id
        uow.audit.record(
            AuditEntry(
                organisation_id=organisation_id,
                actor=actor,
                action=action,
                target_type="approval_request",
                target_id=request.id,
                outcome=outcome,
                reason=reason,
                detail=payload,
            )
        )
        uow.events.publish(
            DomainEvent(
                event_type=event_type,
                organisation_id=organisation_id,
                aggregate_type="approval_request",
                aggregate_id=request.id,
                payload=payload,
            )
        )
