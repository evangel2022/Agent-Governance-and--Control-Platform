"""Role and permission administration (FR-003 to FR-008, FR-031).

Three rules shape this module:

* **A new role grants nothing.** That is not an omission, it is the required
  starting state (FR-004): access is granted by binding permissions, one at a
  time, and each binding is recorded.
* **The five built-in roles are untouchable** (FR-031). They are identified by
  having no organisation, and every attempt to amend, retire or re-bind them is
  refused rather than ignored.
* **Every change invalidates the decision cache.** A role's permissions change
  the effective access of everyone holding it, so the change must be visible at
  the next verification rather than at the end of a TTL (FR-020).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from gov.api.application.permission.audit import (
    PERMISSION_BOUND,
    PERMISSION_UNBOUND,
    ROLE_CREATED,
    ROLE_RETIRED,
    ROLE_UPDATED,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.ports import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RolePermissionRecord,
    RoleRecord,
    UnitOfWork,
    ValidationFailure,
)
from gov.api.domain.permission.catalogue import UnknownPermissionError, get
from gov.api.domain.permission.rules import (
    PermissionRuleError,
    RoleStatus,
    assert_role_is_mutable,
)

NAME_MAX = 200
DESCRIPTION_MAX = 1000


def _translate(error: PermissionRuleError) -> ApplicationError:
    """Map a domain refusal onto the response it deserves."""
    if error.code == "builtin_role_immutable":
        # A distinct authority question, answered as one.
        return ForbiddenError(str(error))
    return ValidationFailure(
        str(error), errors=[{"field": "role", "message": error.message}]
    )


class RoleService:
    """Role and permission administration over a unit of work."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        cache: EffectivePermissionCache | None = None,
    ) -> None:
        self._uow = uow_factory
        self._clock = clock
        self._new_id = new_id
        self._cache = cache

    # ------------------------------------------------------------------- reads

    def list_roles(
        self, *, organisation_id: str, include_retired: bool = False
    ) -> Sequence[RoleRecord]:
        """List the organisation's roles alongside the built-in baseline."""
        with self._uow() as uow:
            return list(
                uow.permissions.list_roles(
                    organisation_id, include_retired=include_retired
                )
            )

    def get_role(self, *, organisation_id: str, role_id: str) -> RoleRecord:
        """Return one role, whether it is the organisation's or a built-in."""
        with self._uow() as uow:
            return self._require(uow, organisation_id, role_id)

    def effective_permissions(
        self, *, organisation_id: str, role_id: str
    ) -> frozenset[str]:
        """Return the permissions a role currently grants."""
        with self._uow() as uow:
            role = self._require(uow, organisation_id, role_id)
            return frozenset(
                binding.permission_name
                for binding in uow.permissions.list_bindings(
                    organisation_id, role.id, role_is_builtin=role.is_builtin
                )
            )

    # ------------------------------------------------------------------ writes

    def create_role(
        self,
        *,
        organisation_id: str,
        name: str,
        description: str,
        actor: str,
    ) -> RoleRecord:
        """Create a role that grants nothing until permissions are bound.

        Raises:
            ValidationFailure: for a missing or over-long field.
            ConflictError: when the name is already used in this organisation.
        """
        checked_name = self._require_text(name, "name", max_length=NAME_MAX)
        checked_description = self._require_text(
            description, "description", max_length=DESCRIPTION_MAX
        )

        with self._uow() as uow:
            if uow.permissions.find_role_by_name(organisation_id, checked_name) is not None:
                raise ConflictError(
                    f"a role named {checked_name!r} already exists",
                    errors=[{"field": "name", "message": "already used"}],
                )

            record = RoleRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                # Organisation roles carry no code: codes belong to the built-ins.
                code=None,
                name=checked_name,
                description=checked_description,
                status=RoleStatus.ACTIVE.value,
                created_at=self._clock(),
            )
            uow.permissions.add_role(record)
            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=ROLE_CREATED,
                role=record,
                detail={"name": checked_name},
            )
            self._invalidate(organisation_id)
        return record

    def update_role(
        self,
        *,
        organisation_id: str,
        role_id: str,
        actor: str,
        description: str | None = None,
        status: str | None = None,
    ) -> RoleRecord:
        """Amend a role's description, or retire it.

        Raises:
            ForbiddenError: when the role is one of the five built-ins.
        """
        checked_description = (
            self._require_text(description, "description", max_length=DESCRIPTION_MAX)
            if description is not None
            else None
        )
        if status is not None and status not in {member.value for member in RoleStatus}:
            raise ValidationFailure(
                f"unknown role status: {status!r}",
                errors=[{"field": "status", "message": "must be active or retired"}],
            )

        with self._uow() as uow:
            record = self._require(uow, organisation_id, role_id)
            self._assert_mutable(record)

            if checked_description is not None:
                record.description = checked_description
            retiring = status == RoleStatus.RETIRED.value
            if status is not None:
                record.status = status
            uow.permissions.update_role(record)

            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=ROLE_RETIRED if retiring else ROLE_UPDATED,
                role=record,
                reason="role retired" if retiring else None,
            )
            self._invalidate(organisation_id)
        return record

    def bind_permission(
        self,
        *,
        organisation_id: str,
        role_id: str,
        permission_name: str,
        actor: str,
        rationale: str | None = None,
    ) -> RolePermissionRecord:
        """Bind a permission to a role.

        Raises:
            ValidationFailure: when the permission name is not catalogued (FR-008).
            ForbiddenError: when the role is a built-in.
            ConflictError: when the permission is already bound.
        """
        try:
            definition = get(permission_name)
        except UnknownPermissionError as error:
            raise ValidationFailure(
                str(error),
                errors=[{"field": "permission_name", "message": "unknown permission"}],
            ) from error

        with self._uow() as uow:
            role = self._require(uow, organisation_id, role_id)
            self._assert_mutable(role)
            if (
                uow.permissions.find_binding(
                    organisation_id, role.id, definition.name
                )
                is not None
            ):
                raise ConflictError(
                    f"{definition.name} is already bound to this role"
                )

            record = RolePermissionRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                role_id=role.id,
                permission_name=definition.name,
                granted_by=actor,
                granted_at=self._clock(),
                rationale=rationale,
            )
            uow.permissions.add_binding(record)
            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=PERMISSION_BOUND,
                role=role,
                detail={"permission_name": definition.name},
            )
            self._invalidate(organisation_id)
        return record

    def unbind_permission(
        self,
        *,
        organisation_id: str,
        role_id: str,
        permission_name: str,
        actor: str,
        reason: str,
    ) -> None:
        """Remove a permission from a role.

        Raises:
            NotFoundError: when the permission is not bound to this role.
            PermissionChangeError: when no reason is given, because removing a
                permission is the change a reviewer will most want explained.
        """
        with self._uow() as uow:
            role = self._require(uow, organisation_id, role_id)
            self._assert_mutable(role)
            try:
                uow.permissions.remove_binding(
                    organisation_id, role.id, permission_name
                )
            except LookupError as exc:
                raise NotFoundError(
                    f"{permission_name} is not bound to this role"
                ) from exc

            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=PERMISSION_UNBOUND,
                role=role,
                reason=reason,
                detail={"permission_name": permission_name},
            )
            self._invalidate(organisation_id)

    # ----------------------------------------------------------------- helpers

    def _require(
        self, uow: UnitOfWork, organisation_id: str, role_id: str
    ) -> RoleRecord:
        try:
            return uow.permissions.get_role(organisation_id, role_id)
        except LookupError as exc:
            raise NotFoundError(f"role {role_id!r} does not exist") from exc

    def _assert_mutable(self, role: RoleRecord) -> None:
        try:
            assert_role_is_mutable(
                organisation_id=role.organisation_id, role_name=role.name
            )
        except PermissionRuleError as error:
            raise _translate(error) from error

    def _require_text(self, value: str | None, field: str, *, max_length: int) -> str:
        if value is None or not value.strip():
            raise ValidationFailure(
                f"{field} is required",
                errors=[{"field": field, "message": "is required"}],
            )
        if len(value) > max_length:
            raise ValidationFailure(
                f"{field} must be at most {max_length} characters",
                errors=[
                    {
                        "field": field,
                        "message": f"must be at most {max_length} characters",
                    }
                ],
            )
        return value

    def _record(
        self,
        uow: UnitOfWork,
        *,
        organisation_id: str,
        actor: str,
        action: str,
        role: RoleRecord,
        reason: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        PermissionChangeRecorder(audit=uow.audit, events=uow.events, clock=self._clock).record(
            PermissionChange(
                organisation_id=organisation_id,
                actor=actor,
                action=action,
                target_type="role",
                target_id=role.id,
                reason=reason,
                detail=dict(detail or {}),
            )
        )

    def _invalidate(self, organisation_id: str) -> None:
        if self._cache is not None:
            self._cache.bump(organisation_id)
