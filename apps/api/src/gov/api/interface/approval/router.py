"""Approval Center endpoints (FR-017 to FR-022, US3).

The approver's identity comes from the authenticated principal, never from the
request body: a caller must not be able to nominate who decided a request. That
is why the decision body carries only the decision and its reason.

Application errors are translated here into the problem responses the rest of
the API uses, so a caller sees the same error shape everywhere:

- not found -> 404
- the requester deciding their own request -> 403
- a request that is already settled or expired -> 409
- a blank reason or unknown decision -> 422
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gov.api.application.approval.service import ApprovalService
from gov.api.application.ports import ApplicationError
from gov.api.domain.approval.state import ApprovalRequest, ApprovalStatus
from gov.api.domain.identity.permissions import APPROVAL_DECIDE, APPROVAL_READ
from gov.api.interface.errors import translate_application_error
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import (
    get_clock,
    get_principal,
    service_dependency,
)
from gov.api.interface.security.oidc import Principal

router = APIRouter(prefix="/v1/approval-requests", tags=["Approval"])

#: Resolved from the application state; supplied by the composition root.
get_approval_service = service_dependency("approval_service", "approval")


def _decision_body(decision: Any) -> dict[str, Any]:
    return {
        "approver_user_id": decision.approver_user_id,
        "decision": decision.decision,
        "reason": decision.reason,
        "decided_at": decision.decided_at.isoformat(),
    }


def _summary(request: ApprovalRequest, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": request.id,
        "invocation_id": request.invocation_id,
        "requested_by": request.requested_by,
        "status": request.status.value,
        "required_approvals": request.required_approvals,
        "allow_self_approval": request.allow_self_approval,
        "expires_at": request.expires_at.isoformat(),
        "decisions": [_decision_body(item) for item in request.decisions],
        "evidence": evidence,
    }


class DecisionBody(BaseModel):
    """The approver's decision. The approver is taken from the principal."""

    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=1, max_length=2000)


@router.get("", dependencies=[Depends(require_permissions(APPROVAL_READ))])
async def list_requests(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    status_filter: Annotated[ApprovalStatus, Query(alias="status")] = (
        ApprovalStatus.PENDING
    ),
) -> dict[str, Any]:
    """List approval requests in a given state, defaulting to the pending queue."""
    requests = service.list_by_status(
        organisation_id=principal.organisation_id, status=status_filter
    )
    items = [
        _summary(item, service.evidence_for(request_id=item.id)) for item in requests
    ]
    return {"items": items, "total": len(items), "next_page_token": None}


@router.get("/{request_id}", dependencies=[Depends(require_permissions(APPROVAL_READ))])
async def get_request(
    request_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> dict[str, Any]:
    """Return one request with the evidence an approver reviews."""
    try:
        found = service.get(
            organisation_id=principal.organisation_id, request_id=request_id
        )
    except ApplicationError as error:
        raise translate_application_error(error) from error
    return _summary(found, service.evidence_for(request_id=found.id))


@router.post(
    "/{request_id}/decisions",
    status_code=201,
    dependencies=[Depends(require_permissions(APPROVAL_DECIDE))],
)
async def decide_request(
    request_id: str,
    body: DecisionBody,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> JSONResponse:
    """Approve or reject a request. The approver is the authenticated caller."""
    try:
        decided = service.decide(
            organisation_id=principal.organisation_id,
            request_id=request_id,
            approver_user_id=principal.user_id,
            decision=body.decision,
            reason=body.reason,
            at=clock(),
        )
    except ApplicationError as error:
        raise translate_application_error(error) from error

    return JSONResponse(
        status_code=201,
        content={
            "approval_request_id": decided.id,
            "status": decided.status.value,
            "decisions": [_decision_body(item) for item in decided.decisions],
        },
    )
