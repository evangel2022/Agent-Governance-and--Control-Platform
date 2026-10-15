"""Responsibility endpoints (FR-013, FR-015).

Accountability changes are permission administration, so these routes are
guarded by the same built-in authority as the rest of this surface: a role that
the Permission Center administers must not be able to move accountability for
itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from gov.api.application.permission.responsibility import (
    ResponsibilityService,
    ResponsibilityView,
)
from gov.api.application.ports import ApplicationError
from gov.api.domain.identity.permissions import IDENTITY_MANAGE
from gov.api.interface.errors import translate_application_error
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(tags=["Responsibility"])

get_responsibility_service = service_dependency(
    "responsibility_service", "responsibility"
)


def _fail(error: Exception) -> NoReturn:
    if isinstance(error, ApplicationError):
        raise translate_application_error(error) from error
    raise error


class ResponsibilityChange(BaseModel):
    """A request to move accountability, with the reason that explains it."""

    accountable_user_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class HistoryEntryOut(BaseModel):
    """One recorded change of accountability."""

    action: str
    actor: str
    accountable_user_id: str | None
    occurred_at: datetime | None
    reason: str | None


class ResponsibilityOut(BaseModel):
    """Who is accountable, and how that came to be."""

    agent_id: str
    accountable_user_id: str
    assigned_at: datetime | None
    history: list[HistoryEntryOut]

    @classmethod
    def from_view(cls, view: ResponsibilityView) -> ResponsibilityOut:
        return cls(
            agent_id=view.agent_id,
            accountable_user_id=view.accountable_user_id,
            assigned_at=view.assigned_at,
            history=[
                HistoryEntryOut(
                    action=entry.action,
                    actor=entry.actor,
                    accountable_user_id=entry.accountable_user_id,
                    occurred_at=entry.occurred_at,
                    reason=entry.reason,
                )
                for entry in view.history
            ],
        )


@router.get(
    "/v1/agents/{agent_id}/responsibility",
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def get_responsibility(
    agent_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ResponsibilityService, Depends(get_responsibility_service)],
) -> ResponsibilityOut:
    """Return the accountable person and the transfer history."""
    try:
        view = service.get(
            organisation_id=principal.organisation_id, agent_id=agent_id
        )
    except ApplicationError as error:
        _fail(error)
    return ResponsibilityOut.from_view(view)


@router.post(
    "/v1/agents/{agent_id}/responsibility",
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def assign_responsibility(
    agent_id: str,
    body: ResponsibilityChange,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[ResponsibilityService, Depends(get_responsibility_service)],
) -> ResponsibilityOut:
    """Assign or transfer accountability for an Agent."""
    try:
        view = service.transfer(
            organisation_id=principal.organisation_id,
            agent_id=agent_id,
            accountable_user_id=body.accountable_user_id,
            reason=body.reason,
            actor=principal.user_id,
        )
    except ApplicationError as error:
        _fail(error)
    return ResponsibilityOut.from_view(view)
