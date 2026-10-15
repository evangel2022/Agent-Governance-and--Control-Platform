"""Approval domain: the state machine for high-risk operations."""

from gov.api.domain.approval.state import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalError",
    "ApprovalRequest",
    "ApprovalStatus",
]
