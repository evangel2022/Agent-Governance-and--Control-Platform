"""Assignment endpoints (FR-009 to FR-012, FR-027).

Guarded by the built-in matrix, like the rest of the Permission Center's own
administration surface. Revocation is a `POST` with a reason rather than a
`DELETE`, for the same interoperation reason as unbinding a permission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from gov.api.application.permission.assignments import AssignmentService
from gov.api.application.ports import ApplicationError, RoleAssignmentRecord
from gov.api.domain.identity.permissions import IDENTITY_MANAGE
from gov.api.interface.errors import translate_application_error
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(prefix="/v1/role-assignments", tags=["Assignments"])

get_assignment_service = service_dependency(
    "assignment_service", "role assignment"
)


def _fail(error: Exception) -> NoReturn:
    if isinstance(error, ApplicationError):
        raise translate_application_error(error) from error
    raise error


class AssignmentCreate(BaseModel):
    """A role grant to a user within a scope."""

    user_id: str
    role_id: str
    scope_type: str = Field(pattern="^(organisation|agent|tool)$")
    scope_id: str | None = None
    expires_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=1000)


class RevokeAssignment(BaseModel):
    """A revocation, with the reason that explains it."""

    reason: str = Field(min_length=1, max_length=1000)


class AssignmentOut(BaseModel):
    """An assignment as the API presents it."""

    id: str
    user_id: str
    role_id: str
    scope_type: str
    scope_id: str | None
    expires_at: datetime | None
    granted_by: str
    granted_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None

    @classmethod
    def from_record(cls, record: RoleAssignmentRecord) -> AssignmentOut:
        return cls(
            id=record.id,
            user_id=record.user_id,
            role_id=record.role_id,
            scope_type=record.scope_type,
            scope_id=record.scope_id,
            expires_at=record.expires_at,
            granted_by=record.granted_by,
            granted_at=record.granted_at,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
        )


@router.get("", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))])
async def list_assignments(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
    user_id: Annotated[str | None, Query()] = None,
    role_id: Annotated[str | None, Query()] = None,
    include_ended: Annotated[bool, Query()] = False,
) -> list[AssignmentOut]:
    """List assignments, optionally narrowed to one user or role."""
    records = service.list_assignments(
        organisation_id=principal.organisation_id,
        user_id=user_id,
        role_id=role_id,
        include_ended=include_ended,
    )
    return [AssignmentOut.from_record(record) for record in records]


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def create_assignment(
    body: AssignmentCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
) -> AssignmentOut:
    """Assign a role to a user within a scope."""
    try:
        record = service.assign(
            organisation_id=principal.organisation_id,
            user_id=body.user_id,
            role_id=body.role_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            expires_at=body.expires_at,
            reason=body.reason,
            actor=principal.user_id,
        )
    except ApplicationError as error:
        _fail(error)
    return AssignmentOut.from_record(record)


@router.post(
    "/{assignment_id}/revoke",
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def revoke_assignment(
    assignment_id: str,
    body: RevokeAssignment,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AssignmentService, Depends(get_assignment_service)],
) -> AssignmentOut:
    """Revoke an assignment, recording why."""
    try:
        record = service.revoke(
            organisation_id=principal.organisation_id,
            assignment_id=assignment_id,
            actor=principal.user_id,
            reason=body.reason,
        )
    except ApplicationError as error:
        _fail(error)
    return AssignmentOut.from_record(record)
