"""Scoped role assignments (FR-009 to FR-012, FR-027).

An assignment is the point where a role becomes access. Four rules apply:

* **Scope is validated, not assumed.** An organisation-wide grant must not name
  an id; a resource-scoped grant must name one. A half-specified scope is how a
  grant ends up wider than intended.
* **A duplicate is refused** rather than silently creating a second grant -
  otherwise revoking one leaves the access in place through the other.
* **Revocation carries a reason** and takes effect at the next verification,
  because the decision cache is invalidated as part of the change (FR-020).
* **The last authority cannot be removed** (FR-027). An organisation that revokes
  its own ability to administer permissions has no way back, so the change is
  refused while it is still a decision rather than an incident.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from gov.api.application.permission.audit import (
    ASSIGNMENT_CREATED,
    ASSIGNMENT_REVOKED,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.permission.effective import EffectivePermissionCache
from gov.api.application.ports import (
    ConflictError,
    NotFoundError,
    RoleAssignmentRecord,
    UnitOfWork,
    ValidationFailure,
)
from gov.api.domain.identity.permissions import IDENTITY_MANAGE
from gov.api.domain.permission.rules import (
    PermissionRuleError,
    RoleStatus,
    is_effective,
    validate_scope,
)


class AssignmentService:
    """Role assignment administration over a unit of work."""

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

    # ------------------------------------------------------------------ reads

    def list_assignments(
        self,
        *,
        organisation_id: str,
        user_id: str | None = None,
        role_id: str | None = None,
        include_ended: bool = False,
    ) -> Sequence[RoleAssignmentRecord]:
        """List assignments, optionally narrowed to one user or role."""
        with self._uow() as uow:
            return list(
                uow.assignments.list_assignments(
                    organisation_id,
                    user_id=user_id,
                    role_id=role_id,
                    include_ended=include_ended,
                )
            )

    # ----------------------------------------------------------------- writes

    def assign(
        self,
        *,
        organisation_id: str,
        user_id: str,
        role_id: str,
        scope_type: str,
        reason: str,
        actor: str,
        scope_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> RoleAssignmentRecord:
        """Grant a role to a user within a scope.

        Raises:
            ValidationFailure: for an inconsistent scope or a missing reason.
            NotFoundError: when the user or role is not visible here.
            ConflictError: when the same grant already exists, or the role is
                retired and therefore grants nothing.
        """
        self._require_reason(reason, "a reason is required to assign a role")
        try:
            validate_scope(scope_type=scope_type, scope_id=scope_id)
        except PermissionRuleError as error:
            raise ValidationFailure(
                str(error), errors=[{"field": "scope_type", "message": error.message}]
            ) from error

        with self._uow() as uow:
            try:
                uow.users.get_user(organisation_id, user_id)
            except LookupError as exc:
                raise NotFoundError(f"user {user_id!r} does not exist") from exc
            try:
                role = uow.permissions.get_role(organisation_id, role_id)
            except LookupError as exc:
                raise NotFoundError(f"role {role_id!r} does not exist") from exc
            if role.status != RoleStatus.ACTIVE.value:
                raise ConflictError(
                    f"role {role.name!r} is retired and grants nothing",
                    errors=[{"field": "role_id", "message": "role is retired"}],
                )
            if (
                uow.assignments.find_assignment(
                    organisation_id, user_id, role_id, scope_type, scope_id
                )
                is not None
            ):
                raise ConflictError(
                    "this role is already assigned to this user in this scope"
                )

            record = RoleAssignmentRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                user_id=user_id,
                role_id=role_id,
                scope_type=scope_type,
                scope_id=scope_id,
                expires_at=expires_at,
                granted_by=actor,
                granted_at=self._clock(),
            )
            uow.assignments.add_assignment(record)
            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=ASSIGNMENT_CREATED,
                assignment=record,
                reason=reason,
            )
            self._invalidate(organisation_id)
        return record

    def revoke(
        self,
        *,
        organisation_id: str,
        assignment_id: str,
        actor: str,
        reason: str,
    ) -> RoleAssignmentRecord:
        """Revoke an assignment, recording why.

        Raises:
            ValidationFailure: when no reason is given.
            NotFoundError: when the assignment is not visible here.
            ConflictError: when it is already ended, or when removing it would
                leave the organisation unable to manage permissions (FR-027).
        """
        self._require_reason(reason, "a reason is required to revoke an assignment")

        with self._uow() as uow:
            try:
                record = uow.assignments.get_assignment(organisation_id, assignment_id)
            except LookupError as exc:
                raise NotFoundError(
                    f"assignment {assignment_id!r} does not exist"
                ) from exc

            now = self._clock()
            if not is_effective(
                revoked_at=record.revoked_at, expires_at=record.expires_at, at=now
            ):
                raise ConflictError("this assignment is no longer in effect")

            remaining = self._managers(
                uow, organisation_id, at=now, excluding=record.id
            )
            if record.role_id in self._managing_roles(uow, organisation_id) and remaining == 0:
                raise ConflictError(
                    "refused: this is the last authority able to manage permissions",
                    errors=[{"field": "assignment_id", "message": "last authority"}],
                )

            record.revoked_at = now
            record.revocation_reason = reason
            uow.assignments.update_assignment(record)
            self._record(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action=ASSIGNMENT_REVOKED,
                assignment=record,
                reason=reason,
            )
            self._invalidate(organisation_id)
        return record

    # --------------------------------------------------------------- helpers

    def _managing_roles(self, uow: UnitOfWork, organisation_id: str) -> frozenset[str]:
        """Role ids that grant the authority to manage permissions."""
        roles = uow.permissions.list_roles(organisation_id, include_retired=True)
        managing: set[str] = set()
        for role in roles:
            bindings = uow.permissions.list_bindings(
                organisation_id, role.id, role_is_builtin=role.is_builtin
            )
            if any(
                binding.permission_name == IDENTITY_MANAGE for binding in bindings
            ):
                managing.add(role.id)
        return frozenset(managing)

    def _managers(
        self,
        uow: UnitOfWork,
        organisation_id: str,
        *,
        at: datetime,
        excluding: str,
    ) -> int:
        """Distinct active users who would still hold the managing authority."""
        managing_roles = self._managing_roles(uow, organisation_id)
        holders: set[str] = set()
        for assignment in uow.assignments.list_assignments(organisation_id):
            if assignment.id == excluding or assignment.role_id not in managing_roles:
                continue
            if not is_effective(
                revoked_at=assignment.revoked_at,
                expires_at=assignment.expires_at,
                at=at,
            ):
                continue
            try:
                user = uow.users.get_user(organisation_id, assignment.user_id)
            except LookupError:
                continue
            if user.status == "active":
                holders.add(user.id)
        return len(holders)

    def _require_reason(self, reason: str | None, message: str) -> str:
        if not (reason or "").strip():
            raise ValidationFailure(
                message, errors=[{"field": "reason", "message": "is required"}]
            )
        return reason  # type: ignore[return-value]

    def _record(
        self,
        uow: UnitOfWork,
        *,
        organisation_id: str,
        actor: str,
        action: str,
        assignment: RoleAssignmentRecord,
        reason: str,
    ) -> None:
        PermissionChangeRecorder(audit=uow.audit, events=uow.events, clock=self._clock).record(
            PermissionChange(
                organisation_id=organisation_id,
                actor=actor,
                action=action,
                target_type="role_assignment",
                target_id=assignment.id,
                reason=reason,
                detail={
                    "user_id": assignment.user_id,
                    "role_id": assignment.role_id,
                    "scope_type": assignment.scope_type,
                    "scope_id": assignment.scope_id,
                },
            )
        )

    def _invalidate(self, organisation_id: str) -> None:
        if self._cache is not None:
            self._cache.bump(organisation_id)
