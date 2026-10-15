"""Role and permission administration endpoints (FR-003 to FR-008, FR-031).

Like the user surface, these routes are guarded by the **built-in** permission
matrix rather than by the permissions the Permission Center administers. If its
own administration surface were governed by roles it manages, an organisation
could grant itself the ability to administer roles; the guarantee would be
circular.

A permission is addressed by its **name**, not by a row id. The catalogue is
platform-wide reference data and FR-007 makes the name the stable identifier, so
the name is the natural key in a path and does not change when the table is
re-seeded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from gov.api.application.permission.roles import RoleService
from gov.api.application.ports import ApplicationError, RoleRecord
from gov.api.domain.identity.permissions import IDENTITY_MANAGE
from gov.api.domain.permission.catalogue import CATALOGUE, PermissionDefinition
from gov.api.interface.errors import translate_application_error
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(tags=["Roles"])

get_role_service = service_dependency("role_service", "role")


def _fail(error: Exception) -> NoReturn:
    if isinstance(error, ApplicationError):
        raise translate_application_error(error) from error
    raise error


class PermissionOut(BaseModel):
    """One catalogued action."""

    name: str
    resource: str
    action: str
    description: str
    is_builtin: bool

    @classmethod
    def from_definition(cls, definition: PermissionDefinition) -> PermissionOut:
        return cls(
            name=definition.name,
            resource=definition.resource,
            action=definition.action,
            description=definition.description,
            is_builtin=definition.is_builtin,
        )


class RoleCreate(BaseModel):
    """A new role. It grants nothing until permissions are bound."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)


class RoleUpdate(BaseModel):
    """The mutable attributes of a role."""

    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, pattern="^(active|retired)$")


class RoleOut(BaseModel):
    """A role and what it currently grants."""

    id: str
    code: str | None
    name: str
    description: str
    status: str
    is_builtin: bool
    permissions: list[str]
    created_at: datetime | None

    @classmethod
    def from_record(
        cls, record: RoleRecord, permissions: frozenset[str]
    ) -> RoleOut:
        return cls(
            id=record.id,
            code=record.code,
            name=record.name,
            description=record.description,
            status=record.status,
            is_builtin=record.is_builtin,
            permissions=sorted(permissions),
            created_at=record.created_at,
        )


class PermissionBindingIn(BaseModel):
    """A permission to bind to a role."""

    permission_name: str = Field(min_length=1, max_length=200)
    rationale: str | None = Field(default=None, max_length=1000)


class PermissionBindingOut(BaseModel):
    """The binding that was created."""

    role_id: str
    permission_name: str
    granted_by: str
    granted_at: datetime
    rationale: str | None


class UnbindRequest(BaseModel):
    """Removing a permission needs a reason, so the body carries one."""

    reason: str = Field(min_length=1, max_length=1000)


@router.get(
    "/v1/permissions", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def list_permissions(
    principal: Annotated[Principal, Depends(get_principal)],
    resource: Annotated[str | None, Query()] = None,
) -> list[PermissionOut]:
    """List the catalogue, optionally narrowed to one resource family."""
    return [
        PermissionOut.from_definition(item)
        for item in CATALOGUE
        if resource is None or item.resource == resource
    ]


@router.get("/v1/roles", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))])
async def list_roles(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[RoleOut]:
    """List roles, including the immutable built-in roles."""
    records = service.list_roles(
        organisation_id=principal.organisation_id,
        include_retired=status_filter != "active",
    )
    return [
        RoleOut.from_record(
            record,
            service.effective_permissions(
                organisation_id=principal.organisation_id, role_id=record.id
            ),
        )
        for record in records
    ]


@router.post(
    "/v1/roles",
    status_code=201,
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def create_role(
    body: RoleCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleOut:
    """Create a role that grants nothing."""
    try:
        record = service.create_role(
            organisation_id=principal.organisation_id,
            name=body.name,
            description=body.description,
            actor=principal.user_id,
        )
    except ApplicationError as error:
        _fail(error)
    return RoleOut.from_record(record, frozenset())


@router.get(
    "/v1/roles/{role_id}", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def get_role(
    role_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleOut:
    """Return a role with the permissions it grants."""
    try:
        record = service.get_role(
            organisation_id=principal.organisation_id, role_id=role_id
        )
        permissions = service.effective_permissions(
            organisation_id=principal.organisation_id, role_id=role_id
        )
    except ApplicationError as error:
        _fail(error)
    return RoleOut.from_record(record, permissions)


@router.patch(
    "/v1/roles/{role_id}", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def update_role(
    role_id: str,
    body: RoleUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleOut:
    """Amend a role, or retire it. Built-in roles are refused."""
    try:
        record = service.update_role(
            organisation_id=principal.organisation_id,
            role_id=role_id,
            actor=principal.user_id,
            description=body.description,
            status=body.status,
        )
        permissions = service.effective_permissions(
            organisation_id=principal.organisation_id, role_id=role_id
        )
    except ApplicationError as error:
        _fail(error)
    return RoleOut.from_record(record, permissions)


@router.get(
    "/v1/roles/{role_id}/permissions",
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def list_role_permissions(
    role_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> list[PermissionOut]:
    """List what a role grants, described by the catalogue."""
    try:
        granted = service.effective_permissions(
            organisation_id=principal.organisation_id, role_id=role_id
        )
    except ApplicationError as error:
        _fail(error)
    return [
        PermissionOut.from_definition(item)
        for item in CATALOGUE
        if item.name in granted
    ]


@router.post(
    "/v1/roles/{role_id}/permissions",
    status_code=201,
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def bind_role_permission(
    role_id: str,
    body: PermissionBindingIn,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> PermissionBindingOut:
    """Bind a permission to a role."""
    try:
        binding = service.bind_permission(
            organisation_id=principal.organisation_id,
            role_id=role_id,
            permission_name=body.permission_name,
            actor=principal.user_id,
            rationale=body.rationale,
        )
    except ApplicationError as error:
        _fail(error)
    return PermissionBindingOut(
        role_id=binding.role_id,
        permission_name=binding.permission_name,
        granted_by=binding.granted_by,
        granted_at=binding.granted_at,
        rationale=binding.rationale,
    )


@router.post(
    "/v1/roles/{role_id}/permissions/{permission_name}/unbind",
    status_code=204,
    dependencies=[Depends(require_permissions(IDENTITY_MANAGE))],
)
async def unbind_role_permission(
    role_id: str,
    permission_name: str,
    body: UnbindRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> Response:
    """Remove a permission from a role, recording why.

    A `POST` rather than a `DELETE`, for the same reason the assignment revoke
    is: the change requires a reason, and a request body on `DELETE` is not
    reliably carried by clients.
    """
    try:
        service.unbind_permission(
            organisation_id=principal.organisation_id,
            role_id=role_id,
            permission_name=permission_name,
            actor=principal.user_id,
            reason=body.reason,
        )
    except ApplicationError as error:
        _fail(error)
    return Response(status_code=204)
