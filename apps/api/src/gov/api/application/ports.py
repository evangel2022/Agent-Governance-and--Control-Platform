"""Ports the application layer depends on.

The use cases below are written against these protocols rather than against a
database session, which is what lets transaction and emission behaviour be
verified without PostgreSQL. The concrete adapters (SQLAlchemy repositories, the
audit writer, the outbox publisher) live in the infrastructure layer and are
supplied at wiring time.

`UnitOfWork` is the transaction boundary. Booking the repository, the audit sink
and the event publisher on the same unit of work is what makes "an audit row and
an outbox row for every successful mutation, and no rows at all for a rejected
one" (T041) a property of the design rather than a hope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol

from gov.api.domain.approval.state import ApprovalRequest, ApprovalStatus
from gov.api.domain.registry.entities import ToolPermission


class ApplicationError(Exception):
    """An error the interface layer can translate into a problem response."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        errors: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        #: Per-field detail, so a validation failure can name what is wrong.
        self.errors: tuple[dict[str, Any], ...] = tuple(dict(item) for item in errors)


class ConflictError(ApplicationError):
    """The request conflicts with existing state."""

    def __init__(
        self, message: str, *, errors: Iterable[Mapping[str, Any]] = ()
    ) -> None:
        super().__init__("conflict", message, errors=errors)


class NotFoundError(ApplicationError):
    """The target does not exist, or is not visible to this organisation."""

    def __init__(
        self, message: str, *, errors: Iterable[Mapping[str, Any]] = ()
    ) -> None:
        super().__init__("not_found", message, errors=errors)


class ForbiddenError(ApplicationError):
    """The caller is not permitted to perform this action."""

    def __init__(
        self, message: str, *, errors: Iterable[Mapping[str, Any]] = ()
    ) -> None:
        super().__init__("forbidden", message, errors=errors)


class ValidationFailure(ApplicationError):
    """The request violated a domain rule."""

    def __init__(
        self, message: str, *, errors: Iterable[Mapping[str, Any]] = ()
    ) -> None:
        super().__init__("validation_error", message, errors=errors)


@dataclass(slots=True)
class AgentRecord:
    id: str
    organisation_id: str
    name: str
    owner_user_id: str
    created_at: datetime
    updated_at: datetime
    status: str = "draft"
    description: str | None = None
    active_version_id: str | None = None


@dataclass(slots=True)
class AgentVersionRecord:
    id: str
    organisation_id: str
    agent_id: str
    version: str
    owner_user_id: str
    created_at: datetime
    updated_at: datetime
    status: str = "draft"
    model_id: str | None = None
    released_at: datetime | None = None


@dataclass(slots=True)
class ToolRecord:
    id: str
    organisation_id: str
    name: str
    risk_level: str
    risk_basis: str
    adapter_ref: str
    permissions: tuple[ToolPermission, ...]
    created_at: datetime
    updated_at: datetime
    status: str = "draft"
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audit event, written inside the mutation's transaction."""

    organisation_id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    outcome: str
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    #: When the change happened, as opposed to when the row was written. Carried
    #: here because a history query answers "when", and the writer is the only
    #: place that knows.
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """One domain event, published through the transactional outbox."""

    event_type: str
    organisation_id: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class RegistryRepository(Protocol):
    """Persistence for Agents, their versions and Tools."""

    def find_agent_by_name(self, organisation_id: str, name: str) -> AgentRecord | None: ...

    def get_agent(self, organisation_id: str, agent_id: str) -> AgentRecord: ...

    def list_agents(
        self,
        organisation_id: str,
        *,
        status: str | None = None,
        owner_user_id: str | None = None,
    ) -> Sequence[AgentRecord]: ...

    def add_agent(self, record: AgentRecord) -> None: ...

    def update_agent(self, record: AgentRecord) -> None: ...

    def find_version(
        self, organisation_id: str, agent_id: str, version: str
    ) -> AgentVersionRecord | None: ...

    def list_versions(
        self, organisation_id: str, agent_id: str
    ) -> Sequence[AgentVersionRecord]: ...

    def add_version(self, record: AgentVersionRecord) -> None: ...

    def update_version(self, record: AgentVersionRecord) -> None: ...

    def released_version(
        self, organisation_id: str, agent_id: str
    ) -> AgentVersionRecord | None: ...

    def find_tool_by_name(self, organisation_id: str, name: str) -> ToolRecord | None: ...

    def get_tool(self, organisation_id: str, tool_id: str) -> ToolRecord: ...

    def add_tool(self, record: ToolRecord) -> None: ...

    def update_tool(self, record: ToolRecord) -> None: ...


class AuditPort(Protocol):
    """The audit trail as the application sees it: append, then read back.

    One port for one concept. The persistence adapter may well split the two
    sides internally - an append-only write path and a read model - but the
    application talks to the trail, not to its storage.
    """

    def record(self, entry: AuditEntry) -> None: ...

    def history_for(
        self, *, organisation_id: str, target_type: str, target_id: str
    ) -> Sequence[AuditEntry]: ...

    def search(
        self,
        *,
        organisation_id: str,
        target_type: str | None = None,
        target_id: str | None = None,
        actor: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[AuditEntry]: ...


class EventPort(Protocol):
    """Publishes a domain event through the transactional outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class ApprovalRepository(Protocol):
    """Persistence for approval requests and their decisions.

    The domain `ApprovalRequest` is the aggregate: it owns the decision list and
    the state machine, so the repository stores and retrieves it rather than
    re-modelling the same rules in a record type.
    """

    def add(self, request: ApprovalRequest) -> None: ...

    def get(self, organisation_id: str, request_id: str) -> ApprovalRequest: ...

    def save(self, request: ApprovalRequest) -> None: ...

    def list_by_status(
        self, organisation_id: str, status: ApprovalStatus = ApprovalStatus.PENDING
    ) -> Sequence[ApprovalRequest]: ...


@dataclass(slots=True)
class UserRecord:
    id: str
    organisation_id: str
    external_subject: str
    display_name: str
    email: str
    status: str = "active"
    last_seen_at: datetime | None = None


@dataclass(slots=True)
class RoleRecord:
    id: str
    organisation_id: str | None
    code: str | None
    name: str
    description: str
    status: str = "active"
    created_at: datetime | None = None

    @property
    def is_builtin(self) -> bool:
        """Built-in roles have no organisation, and cannot be amended (FR-031)."""
        return self.organisation_id is None


@dataclass(slots=True)
class RolePermissionRecord:
    """One permission bound to a role (FR-006)."""

    id: str
    organisation_id: str
    role_id: str
    permission_name: str
    granted_by: str
    granted_at: datetime
    rationale: str | None = None


@dataclass(slots=True)
class RoleAssignmentRecord:
    """One scoped, optionally time-bound grant of a role to a user (FR-009-011)."""

    id: str
    organisation_id: str
    user_id: str
    role_id: str
    scope_type: str
    granted_by: str
    granted_at: datetime
    scope_id: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None


class PermissionRepository(Protocol):
    """The permission catalogue, roles and the bindings between them."""

    def list_roles(
        self, organisation_id: str, *, include_retired: bool = False
    ) -> Sequence[RoleRecord]: ...

    def get_role(self, organisation_id: str, role_id: str) -> RoleRecord: ...

    def find_role_by_name(self, organisation_id: str, name: str) -> RoleRecord | None: ...

    def add_role(self, record: RoleRecord) -> None: ...

    def update_role(self, record: RoleRecord) -> None: ...

    def list_bindings(
        self, organisation_id: str, role_id: str, *, role_is_builtin: bool = False
    ) -> Sequence[RolePermissionRecord]: ...

    def find_binding(
        self, organisation_id: str, role_id: str, permission_name: str
    ) -> RolePermissionRecord | None: ...

    def add_binding(self, record: RolePermissionRecord) -> None: ...

    def remove_binding(
        self, organisation_id: str, role_id: str, permission_name: str
    ) -> None: ...


class AssignmentRepository(Protocol):
    """Scoped grants of roles to users."""

    def list_assignments(
        self,
        organisation_id: str,
        *,
        user_id: str | None = None,
        role_id: str | None = None,
        include_ended: bool = False,
    ) -> Sequence[RoleAssignmentRecord]: ...

    def get_assignment(
        self, organisation_id: str, assignment_id: str
    ) -> RoleAssignmentRecord: ...

    def find_assignment(
        self,
        organisation_id: str,
        user_id: str,
        role_id: str,
        scope_type: str,
        scope_id: str | None,
    ) -> RoleAssignmentRecord | None: ...

    def add_assignment(self, record: RoleAssignmentRecord) -> None: ...

    def update_assignment(self, record: RoleAssignmentRecord) -> None: ...


class UserRepository(Protocol):
    """People roles are assigned to (FR-001, FR-002)."""

    def list_users(self, organisation_id: str) -> Sequence[UserRecord]: ...

    def get_user(self, organisation_id: str, user_id: str) -> UserRecord: ...

    def find_user_by_subject(
        self, organisation_id: str, external_subject: str
    ) -> UserRecord | None: ...

    def add_user(self, record: UserRecord) -> None: ...

    def update_user(self, record: UserRecord) -> None: ...


class UnitOfWork(Protocol):
    """A single transaction boundary."""

    agents: RegistryRepository
    approvals: ApprovalRepository
    permissions: PermissionRepository
    assignments: AssignmentRepository
    users: UserRepository
    audit: AuditPort
    events: EventPort

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """The decision component's answer, with the rules that produced it."""

    allowed: bool
    reason: str
    sources: tuple[str, ...] = ()
    degraded: bool = False

    @property
    def effect(self) -> str:
        return "allow" if self.allowed else "deny"


class DecisionUnavailable(RuntimeError):
    """The decision could not be obtained, so the request must be refused.

    Part of the engine port rather than of any adapter, because the caller has to
    distinguish "denied" from "could not be decided" in order to answer 403 or
    503. An outage must never be reported as a permission decision.
    """


class AuthorizationEngine(Protocol):
    """Whatever decides whether an action is allowed (ADR-0011)."""

    async def decide(self, decision_input: Mapping[str, Any]) -> AuthorizationDecision: ...
