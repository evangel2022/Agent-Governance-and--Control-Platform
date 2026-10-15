"""Audit Center endpoints (FR-023, US5).

Read-only by construction. There is no route here that amends or removes an
audit record, and a test asserts that none appears: the trail's value is that
what it says cannot be edited later, so the absence is part of the contract
rather than an oversight.

The auditor's authority is `audit.read`, which the built-in matrix gives to the
Auditor and to Security and Compliance. Nothing here requires a write permission,
because nothing here writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from gov.api.application.audit.queries import AuditFilter, AuditQueryService
from gov.api.application.ports import AuditEntry
from gov.api.domain.identity.permissions import AUDIT_READ
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(prefix="/v1/audit-events", tags=["Audit"])

get_audit_service = service_dependency("audit_service", "audit")


def _serialise(entry: AuditEntry) -> dict[str, Any]:
    return {
        "id": entry.detail.get("id"),
        "actor": entry.actor,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "outcome": entry.outcome,
        "reason": entry.reason,
        "detail": entry.detail,
        "occurred_at": entry.occurred_at,
    }


@router.get("", dependencies=[Depends(require_permissions(AUDIT_READ))])
async def search_audit_events(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AuditQueryService, Depends(get_audit_service)],
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[str | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Search the trail by target, actor, outcome and time."""
    entries = service.search(
        organisation_id=principal.organisation_id,
        criteria=AuditFilter(
            target_type=target_type,
            target_id=target_id,
            actor=actor,
            outcome=outcome,
            since=since,
            until=until,
        ),
    )
    return [_serialise(entry) for entry in entries]


@router.get("/{target_type}/{target_id}", dependencies=[Depends(require_permissions(AUDIT_READ))])
async def reconstruct_target(
    target_type: str,
    target_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AuditQueryService, Depends(get_audit_service)],
) -> list[dict[str, Any]]:
    """Return every recorded change to one target, oldest first.

    This is the reconstruction an auditor performs: the chain of events that
    explains how a thing came to be as it is.
    """
    entries = service.reconstruct(
        organisation_id=principal.organisation_id,
        target_type=target_type,
        target_id=target_id,
    )
    return [_serialise(entry) for entry in entries]
