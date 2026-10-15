"""Unit tests for the approval use cases (T065, US3)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork

from gov.api.application.approval.service import ApprovalService
from gov.api.application.ports import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailure,
)
from gov.api.domain.approval.state import ApprovalStatus

ORG = "org-1"
REQUESTER = "user-requester"
APPROVER = "user-approver"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=30)
WINDOW = NOW + timedelta(hours=12)


def _service(*, fail_audit: bool = False) -> tuple[ApprovalService, InMemoryStore]:
    store = InMemoryStore()
    counter = itertools.count(1)
    service = ApprovalService(
        lambda: InMemoryUnitOfWork(store, fail_audit=fail_audit),
        new_id=lambda: f"approval-{next(counter)}",
    )
    return service, store


def _raise(service: ApprovalService, **overrides: object):
    payload: dict[str, object] = {
        "organisation_id": ORG,
        "invocation_id": "inv-1",
        "requested_by": REQUESTER,
        "expires_at": WINDOW,
        "actor": REQUESTER,
    }
    payload.update(overrides)
    return service.raise_request(**payload)  # type: ignore[arg-type]


def test_raising_a_request_persists_it_and_records_the_event() -> None:
    service, store = _service()
    request = _raise(service)

    assert store.approvals[request.id].status is ApprovalStatus.PENDING
    assert len(store.audit) == 1
    assert store.audit[0].action == "request"
    assert store.audit[0].target_type == "approval_request"
    assert store.events[0].event_type == "approval.requested"


def test_a_retry_for_the_same_invocation_does_not_raise_a_second_request() -> None:
    """Quickstart V8: a duplicate request must not duplicate the approval."""
    service, store = _service()
    first = _raise(service)
    second = _raise(service, idempotency_key="key-1")

    assert second.id == first.id
    assert len(store.approvals) == 1
    assert len(store.audit) == 1
    assert len(store.events) == 1


def test_a_retry_after_a_decision_still_finds_the_original_request() -> None:
    service, store = _service()
    request = _raise(service)
    service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision="approve",
        reason="reviewed the invoice batch",
        at=LATER,
    )

    retried = _raise(service)
    assert retried.id == request.id
    assert retried.status is ApprovalStatus.APPROVED
    assert len(store.approvals) == 1


def test_the_pending_queue_lists_only_unsettled_requests() -> None:
    service, _ = _service()
    pending = _raise(service)
    settled = _raise(service, invocation_id="inv-2")
    service.decide(
        organisation_id=ORG,
        request_id=settled.id,
        approver_user_id=APPROVER,
        decision="approve",
        reason="ok",
        at=LATER,
    )

    queue = service.list_by_status(organisation_id=ORG)
    assert [request.id for request in queue] == [pending.id]


def test_a_request_carries_the_evidence_an_approver_reviews() -> None:
    service, _ = _service()
    request = _raise(
        service,
        evidence={"risk_level": "high", "parameters_digest": "sha256:abc"},
    )
    assert service.evidence_for(request_id=request.id) == {
        "risk_level": "high",
        "parameters_digest": "sha256:abc",
    }


def test_getting_an_unknown_request_is_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        service.get(organisation_id=ORG, request_id="missing")


def test_deciding_a_request_records_the_decision_and_its_reason() -> None:
    service, store = _service()
    request = _raise(service)

    decided = service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision="approve",
        reason="checked against the purchase order",
        at=LATER,
    )

    assert decided.status is ApprovalStatus.APPROVED
    assert len(decided.decisions) == 1
    assert decided.decisions[0].approver_user_id == APPROVER
    assert decided.decisions[0].decided_at == LATER
    assert store.audit[-1].action == "approve"
    assert store.audit[-1].reason == "checked against the purchase order"
    assert store.events[-1].event_type == "approval.decided"


def test_a_rejection_settles_the_request() -> None:
    service, _ = _service()
    request = _raise(service)
    decided = service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision="reject",
        reason="amount exceeds the approved threshold",
        at=LATER,
    )
    assert decided.status is ApprovalStatus.REJECTED


def test_the_requester_cannot_approve_their_own_request() -> None:
    """FR-022 default: self-approval is refused, and nothing is recorded."""
    service, store = _service()
    request = _raise(service)
    audits_before = len(store.audit)

    with pytest.raises(ForbiddenError) as excinfo:
        service.decide(
            organisation_id=ORG,
            request_id=request.id,
            approver_user_id=REQUESTER,
            decision="approve",
            reason="self approved",
            at=LATER,
        )

    assert excinfo.value.code == "forbidden"
    assert store.approvals[request.id].status is ApprovalStatus.PENDING
    assert store.approvals[request.id].decisions == []
    assert len(store.audit) == audits_before


def test_self_approval_is_permitted_when_the_request_allows_it() -> None:
    service, _ = _service()
    request = _raise(service, allow_self_approval=True)
    decided = service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=REQUESTER,
        decision="approve",
        reason="policy permits self approval for this tool",
        at=LATER,
    )
    assert decided.status is ApprovalStatus.APPROVED


def test_a_settled_request_cannot_be_decided_again() -> None:
    service, _ = _service()
    request = _raise(service)
    service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision="approve",
        reason="approved",
        at=LATER,
    )
    with pytest.raises(ConflictError) as excinfo:
        service.decide(
            organisation_id=ORG,
            request_id=request.id,
            approver_user_id="user-other",
            decision="reject",
            reason="changed my mind",
            at=LATER,
        )
    assert excinfo.value.code == "conflict"


def test_a_blank_reason_is_a_validation_failure() -> None:
    service, _ = _service()
    request = _raise(service)
    with pytest.raises(ValidationFailure):
        service.decide(
            organisation_id=ORG,
            request_id=request.id,
            approver_user_id=APPROVER,
            decision="approve",
            reason="   ",
            at=LATER,
        )


def test_an_unknown_decision_is_a_validation_failure() -> None:
    service, _ = _service()
    request = _raise(service)
    with pytest.raises(ValidationFailure):
        service.decide(
            organisation_id=ORG,
            request_id=request.id,
            approver_user_id=APPROVER,
            decision="maybe",
            reason="uncertain",
            at=LATER,
        )


def test_dual_control_requires_two_distinct_approvers() -> None:
    service, _ = _service()
    request = _raise(service, required_approvals=2)

    first = service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id="approver-a",
        decision="approve",
        reason="first review",
        at=LATER,
    )
    assert first.status is ApprovalStatus.PENDING

    with pytest.raises(ConflictError):
        service.decide(
            organisation_id=ORG,
            request_id=request.id,
            approver_user_id="approver-a",
            decision="approve",
            reason="second review by the same person",
            at=LATER,
        )

    second = service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id="approver-b",
        decision="approve",
        reason="second review",
        at=LATER,
    )
    assert second.status is ApprovalStatus.APPROVED


def test_expiry_denies_the_request_and_records_a_reason() -> None:
    service, store = _service()
    request = _raise(service)

    assert service.expire_due(organisation_id=ORG, at=WINDOW + timedelta(seconds=1)) == 1
    assert store.approvals[request.id].status is ApprovalStatus.EXPIRED
    assert store.audit[-1].action == "expire"
    assert store.audit[-1].outcome == "denied"
    assert store.audit[-1].reason is not None
    assert store.events[-1].event_type == "approval.expired"


def test_expiry_leaves_requests_inside_their_window_alone() -> None:
    service, store = _service()
    request = _raise(service)
    assert service.expire_due(organisation_id=ORG, at=LATER) == 0
    assert store.approvals[request.id].status is ApprovalStatus.PENDING
    # The only audit entry is the one the request itself wrote; no expiry fired.
    assert [entry.action for entry in store.audit] == ["request"]


def test_expiry_does_not_reopen_a_settled_request() -> None:
    service, store = _service()
    request = _raise(service)
    service.decide(
        organisation_id=ORG,
        request_id=request.id,
        approver_user_id=APPROVER,
        decision="approve",
        reason="approved before the window closed",
        at=LATER,
    )
    assert service.expire_due(organisation_id=ORG, at=WINDOW + timedelta(days=1)) == 0
    assert store.approvals[request.id].status is ApprovalStatus.APPROVED


def test_expiry_only_touches_the_calling_organisation() -> None:
    service, _ = _service()
    _raise(service)
    assert service.expire_due(organisation_id="org-2", at=WINDOW + timedelta(days=1)) == 0


def test_a_failing_audit_write_rolls_the_request_back() -> None:
    service, store = _service(fail_audit=True)
    with pytest.raises(RuntimeError):
        _raise(service)

    assert store.approvals == {}
    assert store.audit == []
    assert store.events == []
