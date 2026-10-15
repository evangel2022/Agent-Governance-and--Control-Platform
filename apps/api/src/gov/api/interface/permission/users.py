"""User administration endpoints (FR-001, FR-002).

These routes are guarded by the **built-in** permission matrix, not by the
permissions the Permission Center administers at runtime. That is deliberate: if
its own administration surface were governed by roles it manages, an organisation
could grant itself the ability to administer roles, and the guarantee would be
circular. The bootstrap path stays on the fixed baseline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from gov.api.application.permission.users import UserService
from gov.api.application.ports import ApplicationError, UserRecord
from gov.api.domain.identity.permissions import IDENTITY_MANAGE
from gov.api.interface.errors import translate_application_error
from gov.api.interface.security.authorize import require_permissions
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(prefix="/v1/users", tags=["Users"])

get_user_service = service_dependency("user_service", "user")


def _fail(error: Exception) -> NoReturn:
    if isinstance(error, ApplicationError):
        raise translate_application_error(error) from error
    raise error


class UserCreate(BaseModel):
    """A new user."""

    external_subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)


class UserUpdate(BaseModel):
    """The mutable attributes of a user."""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    reason: str | None = Field(default=None, max_length=1000)


class UserOut(BaseModel):
    """A user as the API presents them."""

    id: str
    external_subject: str
    display_name: str
    email: str
    status: str
    last_seen_at: datetime | None

    @classmethod
    def from_record(cls, record: UserRecord) -> UserOut:
        return cls(
            id=record.id,
            external_subject=record.external_subject,
            display_name=record.display_name,
            email=record.email,
            status=record.status,
            last_seen_at=record.last_seen_at,
        )


class UserPage(BaseModel):
    """A page of users."""

    items: list[UserOut]
    total: int
    next_page_token: str | None = None


@router.get("", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))])
async def list_users(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserPage:
    """List the caller's organisation's users."""
    records = service.list_users(organisation_id=principal.organisation_id)
    items = [UserOut.from_record(record) for record in records]
    return UserPage(items=items, total=len(items), next_page_token=None)


@router.post(
    "", status_code=201, dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def create_user(
    body: UserCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserOut:
    """Create a user."""
    try:
        record = service.create_user(
            organisation_id=principal.organisation_id,
            external_subject=body.external_subject,
            display_name=body.display_name,
            email=body.email,
            actor=principal.user_id,
        )
    except ApplicationError as error:
        _fail(error)
    return UserOut.from_record(record)


@router.get(
    "/{user_id}", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def get_user(
    user_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserOut:
    """Return one user."""
    try:
        record = service.get_user(
            organisation_id=principal.organisation_id, user_id=user_id
        )
    except ApplicationError as error:
        _fail(error)
    return UserOut.from_record(record)


@router.patch(
    "/{user_id}", dependencies=[Depends(require_permissions(IDENTITY_MANAGE))]
)
async def update_user(
    user_id: str,
    body: UserUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserOut:
    """Amend a user, or disable and re-enable them."""
    try:
        if body.status is not None:
            record = service.set_status(
                organisation_id=principal.organisation_id,
                user_id=user_id,
                actor=principal.user_id,
                active=body.status == "active",
                reason=body.reason,
            )
        else:
            record = service.update_user(
                organisation_id=principal.organisation_id,
                user_id=user_id,
                actor=principal.user_id,
                display_name=body.display_name,
                email=body.email,
            )
    except ApplicationError as error:
        _fail(error)
    return UserOut.from_record(record)
