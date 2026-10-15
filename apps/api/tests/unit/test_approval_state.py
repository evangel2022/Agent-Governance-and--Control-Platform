"""Unit tests for the approval state machine (T064, US3)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from gov.api.domain.approval.state import (
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def _request(**overrides: object) -> ApprovalRequest:
    payload: dict[str, object] = {
        "id": "req-1",
        "organisation_id": "org-1",
        "invocation_id": "inv-1",
        "requested_by": "user-requester",
        "expires_at": NOW + timedelta(hours=12),
    }
    payload.update(overrides)
    return ApprovalRequest(**payload)  # type: ignore[arg-type]


def test_a_new_request_is_pending() -> None:
    request = _request()
    assert request.is_pending is True
    assert request.status is ApprovalStatus.PENDING
    assert request.approvers == frozenset()


def test_single_approver_closes_the_request() -> None:
    request = _request()
    request.decide(
        approver_user_id="user-approver",
        decision="approve",
        reason="reviewed the invoice batch",
        at=LATER,
    )
    assert request.status is ApprovalStatus.APPROVED


def test_rejection_closes_the_request_immediately() -> None:
    request = _request(required_approvals=2)
    request.decide(
        approver_user_id="user-approver",
        decision="reject",
        reason="amount exceeds the approved threshold",
        at=LATER,
    )
    assert request.status is ApprovalStatus.REJECTED


def test_dual_control_needs_two_distinct_approvers() -> None:
    request = _request(required_approvals=2)
    request.decide(
        approver_user_id="approver-a",
        decision="approve",
        reason="checked against the purchase order",
        at=LATER,
    )
    assert request.status is ApprovalStatus.PENDING

    request.decide(
        approver_user_id="approver-b",
        decision="approve",
        reason="second review complete",
        at=LATER,
    )
    assert request.status is ApprovalStatus.APPROVED
    assert request.approvers == frozenset({"approver-a", "approver-b"})


def test_one_approver_cannot_satisfy_dual_control_twice() -> None:
    request = _request(required_approvals=2)
    request.decide(
        approver_user_id="approver-a",
        decision="approve",
        reason="first review",
        at=LATER,
    )
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="approver-a",
            decision="approve",
            reason="second review by the same person",
            at=LATER,
        )
    assert excinfo.value.code == "duplicate_approver"
    assert request.status is ApprovalStatus.PENDING


def test_requester_cannot_approve_their_own_request() -> None:
    request = _request()
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="user-requester",
            decision="approve",
            reason="self approved",
            at=LATER,
        )
    assert excinfo.value.code == "self_approval_forbidden"
    assert request.status is ApprovalStatus.PENDING
    assert request.decisions == []


def test_self_approval_is_allowed_when_policy_permits_it() -> None:
    request = _request(allow_self_approval=True)
    request.decide(
        approver_user_id="user-requester",
        decision="approve",
        reason="policy permits self approval for this tool",
        at=LATER,
    )
    assert request.status is ApprovalStatus.APPROVED


def test_a_decision_must_carry_a_reason() -> None:
    request = _request()
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="user-approver",
            decision="approve",
            reason="   ",
            at=LATER,
        )
    assert excinfo.value.code == "reason_required"


def test_invalid_decision_kind_is_rejected() -> None:
    request = _request()
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="user-approver",
            decision="maybe",
            reason="uncertain",
            at=LATER,
        )
    assert excinfo.value.code == "invalid_decision"


@pytest.mark.parametrize("status", ["approve", "reject"])
def test_a_decided_request_cannot_be_decided_again(status: str) -> None:
    request = _request()
    request.decide(
        approver_user_id="approver-a",
        decision=status,
        reason="first decision",
        at=LATER,
    )
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="approver-b",
            decision="approve",
            reason="attempt to reopen",
            at=LATER,
        )
    assert excinfo.value.code == "not_pending"


def test_decision_records_are_immutable() -> None:
    request = _request()
    decision = request.decide(
        approver_user_id="user-approver",
        decision="approve",
        reason="reviewed",
        at=LATER,
    )
    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed my mind"  # type: ignore[misc]


def test_expiry_after_the_window() -> None:
    request = _request(expires_at=NOW + timedelta(hours=1))
    assert request.expire(at=NOW + timedelta(hours=1, seconds=1)) is True
    assert request.status is ApprovalStatus.EXPIRED


def test_expiry_does_not_fire_before_the_window() -> None:
    request = _request(expires_at=NOW + timedelta(hours=1))
    assert request.expire(at=NOW + timedelta(minutes=30)) is False
    assert request.status is ApprovalStatus.PENDING


def test_expiry_cannot_reopen_a_decided_request() -> None:
    request = _request(expires_at=NOW - timedelta(hours=1))
    request.decide(
        approver_user_id="user-approver",
        decision="approve",
        reason="approved before the window closed",
        at=NOW - timedelta(hours=2),
    )
    assert request.expire(at=NOW) is False
    assert request.status is ApprovalStatus.APPROVED


def test_an_expired_request_can_no_longer_be_approved() -> None:
    request = _request(expires_at=NOW + timedelta(hours=1))
    request.expire(at=NOW + timedelta(hours=2))
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="user-approver",
            decision="approve",
            reason="late approval",
            at=NOW + timedelta(hours=3),
        )
    assert excinfo.value.code == "not_pending"


def test_cancelling_a_pending_request() -> None:
    request = _request()
    request.cancel()
    assert request.status is ApprovalStatus.CANCELLED


def test_a_decided_request_cannot_be_cancelled() -> None:
    request = _request()
    request.decide(
        approver_user_id="user-approver",
        decision="approve",
        reason="approved",
        at=LATER,
    )
    with pytest.raises(ApprovalError):
        request.cancel()


def test_required_approvals_must_be_at_least_one() -> None:
    with pytest.raises(ApprovalError) as excinfo:
        _request(required_approvals=0)
    assert excinfo.value.code == "invalid_required_approvals"


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ApprovalError) as excinfo:
        _request(expires_at=datetime(2026, 10, 13, 21, 0))
    assert excinfo.value.code == "naive_datetime"


def test_naive_decision_time_is_rejected() -> None:
    request = _request()
    with pytest.raises(ApprovalError) as excinfo:
        request.decide(
            approver_user_id="user-approver",
            decision="approve",
            reason="reviewed",
            at=datetime(2026, 10, 13, 10, 0),
        )
    assert excinfo.value.code == "naive_datetime"
