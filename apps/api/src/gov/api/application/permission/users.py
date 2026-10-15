"""User administration (FR-001, FR-002).

Deliberately not a domain entity. A user is three string fields and a status;
the rules are "required", "looks like an address" and "unique within the
organisation", none of which earns a domain object. The validation lives here,
before the transaction opens, so a rejected submission cannot leave a partial
record.

Disabling a user removes their effective permissions immediately, because
`EffectivePermissionResolver` refuses to resolve anything for a user who is not
active - and their history is untouched, because the row is never deleted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from gov.api.application.permission.audit import (
    USER_CREATED,
    USER_DISABLED,
    USER_ENABLED,
    USER_UPDATED,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.ports import (
    ConflictError,
    NotFoundError,
    UnitOfWork,
    UserRecord,
    ValidationFailure,
)

ACTIVE = "active"
DISABLED = "disabled"

EXTERNAL_SUBJECT_MAX = 255
DISPLAY_NAME_MAX = 200
EMAIL_MAX = 320


def _require_text(value: str | None, field: str, *, max_length: int) -> str:
    if value is None or not value.strip():
        raise ValidationFailure(
            f"{field} is required",
            errors=[{"field": field, "message": "is required"}],
        )
    if len(value) > max_length:
        raise ValidationFailure(
            f"{field} must be at most {max_length} characters",
            errors=[{"field": field, "message": f"must be at most {max_length} characters"}],
        )
    return value


def _require_email(value: str | None) -> str:
    checked = _require_text(value, "email", max_length=EMAIL_MAX)
    if "@" not in checked or checked.startswith("@") or checked.endswith("@"):
        raise ValidationFailure(
            "email must look like an address",
            errors=[{"field": "email", "message": "must look like an address"}],
        )
    return checked


class UserService:
    """User administration over a unit of work."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self._uow = uow_factory
        self._clock = clock
        self._new_id = new_id

    def list_users(self, *, organisation_id: str) -> Sequence[UserRecord]:
        """List the organisation's users."""
        with self._uow() as uow:
            return list(uow.users.list_users(organisation_id))

    def get_user(self, *, organisation_id: str, user_id: str) -> UserRecord:
        """Return one user."""
        with self._uow() as uow:
            return self._require(uow, organisation_id, user_id)

    def create_user(
        self,
        *,
        organisation_id: str,
        external_subject: str,
        display_name: str,
        email: str,
        actor: str,
    ) -> UserRecord:
        """Create a user.

        Raises:
            ValidationFailure: for a missing or malformed field.
            ConflictError: when the external subject is already known here.
        """
        subject = _require_text(
            external_subject, "external_subject", max_length=EXTERNAL_SUBJECT_MAX
        )
        name = _require_text(display_name, "display_name", max_length=DISPLAY_NAME_MAX)
        address = _require_email(email)

        with self._uow() as uow:
            if uow.users.find_user_by_subject(organisation_id, subject) is not None:
                raise ConflictError(
                    "a user with this external subject already exists",
                    errors=[
                        {
                            "field": "external_subject",
                            "message": "already used in this organisation",
                        }
                    ],
                )

            record = UserRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                external_subject=subject,
                display_name=name,
                email=address,
            )
            uow.users.add_user(record)
            PermissionChangeRecorder(audit=uow.audit, events=uow.events, clock=self._clock).record(
                PermissionChange(
                    organisation_id=organisation_id,
                    actor=actor,
                    action=USER_CREATED,
                    target_type="user",
                    target_id=record.id,
                    detail={"external_subject": subject},
                )
            )
        return record

    def update_user(
        self,
        *,
        organisation_id: str,
        user_id: str,
        actor: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> UserRecord:
        """Amend a user's display name or address."""
        name = (
            _require_text(display_name, "display_name", max_length=DISPLAY_NAME_MAX)
            if display_name is not None
            else None
        )
        address = _require_email(email) if email is not None else None

        with self._uow() as uow:
            record = self._require(uow, organisation_id, user_id)
            if name is not None:
                record.display_name = name
            if address is not None:
                record.email = address
            uow.users.update_user(record)
            PermissionChangeRecorder(audit=uow.audit, events=uow.events, clock=self._clock).record(
                PermissionChange(
                    organisation_id=organisation_id,
                    actor=actor,
                    action=USER_UPDATED,
                    target_type="user",
                    target_id=record.id,
                )
            )
        return record

    def set_status(
        self,
        *,
        organisation_id: str,
        user_id: str,
        actor: str,
        active: bool,
        reason: str | None = None,
    ) -> UserRecord:
        """Disable or re-enable a user.

        Disabling requires a reason: it removes access, and the reason is what
        later explains why.
        """
        if not active and not (reason or "").strip():
            # Checked here rather than left to the recorder, so the caller gets a
            # field-level validation error rather than an internal failure.
            raise ValidationFailure(
                "a reason is required to disable a user",
                errors=[{"field": "reason", "message": "is required when disabling"}],
            )

        with self._uow() as uow:
            record = self._require(uow, organisation_id, user_id)
            record.status = ACTIVE if active else DISABLED
            uow.users.update_user(record)
            PermissionChangeRecorder(audit=uow.audit, events=uow.events, clock=self._clock).record(
                PermissionChange(
                    organisation_id=organisation_id,
                    actor=actor,
                    action=USER_ENABLED if active else USER_DISABLED,
                    target_type="user",
                    target_id=record.id,
                    reason=reason,
                )
            )
        return record

    def _require(
        self, uow: UnitOfWork, organisation_id: str, user_id: str
    ) -> UserRecord:
        try:
            return uow.users.get_user(organisation_id, user_id)
        except LookupError as exc:
            raise NotFoundError(f"user {user_id!r} does not exist") from exc
