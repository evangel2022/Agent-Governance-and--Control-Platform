"""In-memory implementations of the application ports.

These stand in for the *infrastructure* side of a port, not for the code under
test. The use cases and domain rules exercised through them are the real ones.

The unit of work reproduces transaction semantics - snapshot on entry, restore on
exception - so rollback behaviour is verifiable without PostgreSQL. That is what
makes "no partial record" and "no state change without its audit row" testable
today rather than only after the database adapter exists.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from gov.api.application.ports import (
    AgentRecord,
    AgentVersionRecord,
    AuditEntry,
    AuthorizationDecision,
    DecisionUnavailable,
    DomainEvent,
    RoleAssignmentRecord,
    RolePermissionRecord,
    RoleRecord,
    ToolRecord,
    UserRecord,
)
from gov.api.domain.approval.state import ApprovalRequest, ApprovalStatus
from gov.api.domain.identity.permissions import (
    REGISTRY_WRITE_ANY,
    ROLE_PERMISSIONS,
    ROLES,
)


class InMemoryStore:
    """The mutable state a unit of work reads and writes."""

    def __init__(self) -> None:
        self.agents: dict[str, AgentRecord] = {}
        self.versions: dict[str, AgentVersionRecord] = {}
        self.tools: dict[str, ToolRecord] = {}
        self.approvals: dict[str, ApprovalRequest] = {}
        self.users: dict[str, UserRecord] = {}
        self.roles: dict[str, RoleRecord] = {}
        self.bindings: dict[str, RolePermissionRecord] = {}
        self.assignments: dict[str, RoleAssignmentRecord] = {}
        self.audit: list[AuditEntry] = []
        self.events: list[DomainEvent] = []


class InMemoryRegistryRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ agents

    def find_agent_by_name(self, organisation_id: str, name: str) -> AgentRecord | None:
        return next(
            (
                agent
                for agent in self._store.agents.values()
                if agent.organisation_id == organisation_id and agent.name == name
            ),
            None,
        )

    def get_agent(self, organisation_id: str, agent_id: str) -> AgentRecord:
        agent = self._store.agents.get(agent_id)
        if agent is None or agent.organisation_id != organisation_id:
            raise LookupError(agent_id)
        return agent

    def add_agent(self, record: AgentRecord) -> None:
        self._store.agents[record.id] = record

    def list_agents(
        self,
        organisation_id: str,
        *,
        status: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[AgentRecord]:
        return [
            agent
            for agent in self._store.agents.values()
            if agent.organisation_id == organisation_id
            and (status is None or agent.status == status)
            and (owner_user_id is None or agent.owner_user_id == owner_user_id)
        ]

    def update_agent(self, record: AgentRecord) -> None:
        self._store.agents[record.id] = record

    # ---------------------------------------------------------------- versions

    def find_version(
        self, organisation_id: str, agent_id: str, version: str
    ) -> AgentVersionRecord | None:
        return next(
            (
                item
                for item in self._store.versions.values()
                if item.organisation_id == organisation_id
                and item.agent_id == agent_id
                and item.version == version
            ),
            None,
        )

    def list_versions(
        self, organisation_id: str, agent_id: str
    ) -> list[AgentVersionRecord]:
        return [
            item
            for item in self._store.versions.values()
            if item.organisation_id == organisation_id and item.agent_id == agent_id
        ]

    def add_version(self, record: AgentVersionRecord) -> None:
        self._store.versions[record.id] = record

    def update_version(self, record: AgentVersionRecord) -> None:
        self._store.versions[record.id] = record

    def released_version(
        self, organisation_id: str, agent_id: str
    ) -> AgentVersionRecord | None:
        return next(
            (
                item
                for item in self._store.versions.values()
                if item.organisation_id == organisation_id
                and item.agent_id == agent_id
                and item.status == "released"
            ),
            None,
        )

    # ------------------------------------------------------------------- tools

    def find_tool_by_name(self, organisation_id: str, name: str) -> ToolRecord | None:
        return next(
            (
                tool
                for tool in self._store.tools.values()
                if tool.organisation_id == organisation_id and tool.name == name
            ),
            None,
        )

    def get_tool(self, organisation_id: str, tool_id: str) -> ToolRecord:
        tool = self._store.tools.get(tool_id)
        if tool is None or tool.organisation_id != organisation_id:
            raise LookupError(tool_id)
        return tool

    def add_tool(self, record: ToolRecord) -> None:
        self._store.tools[record.id] = record

    def update_tool(self, record: ToolRecord) -> None:
        self._store.tools[record.id] = record


class InMemoryAudit:
    def __init__(self, store: InMemoryStore, *, fail: bool = False) -> None:
        self._store = store
        self._fail = fail

    def record(self, entry: AuditEntry) -> None:
        if self._fail:
            raise RuntimeError("audit sink is unreachable")
        self._store.audit.append(entry)

    def history_for(
        self, *, organisation_id: str, target_type: str, target_id: str
    ) -> list[AuditEntry]:
        return [
            entry
            for entry in self._store.audit
            if entry.organisation_id == organisation_id
            and entry.target_type == target_type
            and entry.target_id == target_id
        ]

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
    ) -> list[AuditEntry]:
        def matches(entry: AuditEntry) -> bool:
            if entry.organisation_id != organisation_id:
                return False
            if target_type is not None and entry.target_type != target_type:
                return False
            if target_id is not None and entry.target_id != target_id:
                return False
            if actor is not None and entry.actor != actor:
                return False
            if outcome is not None and entry.outcome != outcome:
                return False
            occurred = entry.occurred_at
            if since is not None and (occurred is None or occurred < since):
                return False
            return not (until is not None and (occurred is None or occurred > until))

        return [entry for entry in self._store.audit if matches(entry)]


class InMemoryEvents:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def publish(self, event: DomainEvent) -> None:
        self._store.events.append(event)


class InMemoryApprovalRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def add(self, request: ApprovalRequest) -> None:
        self._store.approvals[request.id] = request

    def get(self, organisation_id: str, request_id: str) -> ApprovalRequest:
        request = self._store.approvals.get(request_id)
        if request is None or request.organisation_id != organisation_id:
            raise LookupError(request_id)
        return request

    def save(self, request: ApprovalRequest) -> None:
        self._store.approvals[request.id] = request

    def list_by_status(
        self, organisation_id: str, status: ApprovalStatus = ApprovalStatus.PENDING
    ) -> list[ApprovalRequest]:
        return [
            request
            for request in self._store.approvals.values()
            if request.organisation_id == organisation_id and request.status is status
        ]


class InMemoryUserRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def list_users(self, organisation_id: str) -> list[UserRecord]:
        return [
            user
            for user in self._store.users.values()
            if user.organisation_id == organisation_id
        ]

    def get_user(self, organisation_id: str, user_id: str) -> UserRecord:
        user = self._store.users.get(user_id)
        if user is None or user.organisation_id != organisation_id:
            raise LookupError(user_id)
        return user

    def find_user_by_subject(
        self, organisation_id: str, external_subject: str
    ) -> UserRecord | None:
        return next(
            (
                user
                for user in self._store.users.values()
                if user.organisation_id == organisation_id
                and user.external_subject == external_subject
            ),
            None,
        )

    def add_user(self, record: UserRecord) -> None:
        self._store.users[record.id] = record

    def update_user(self, record: UserRecord) -> None:
        self._store.users[record.id] = record


class InMemoryPermissionRepository:
    """Roles and bindings, including the built-in roles that have no organisation.

    The duplicate-binding and duplicate-role-name rules are enforced here as they
    would be by the database's unique constraints, so a use-case test exercises
    the same refusal it would meet in production.
    """

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def list_roles(
        self, organisation_id: str, *, include_retired: bool = False
    ) -> list[RoleRecord]:
        return [
            role
            for role in self._store.roles.values()
            if (role.organisation_id in (organisation_id, None))
            and (include_retired or role.status != "retired")
        ]

    def get_role(self, organisation_id: str, role_id: str) -> RoleRecord:
        role = self._store.roles.get(role_id)
        if role is None or role.organisation_id not in (organisation_id, None):
            raise LookupError(role_id)
        return role

    def find_role_by_name(self, organisation_id: str, name: str) -> RoleRecord | None:
        return next(
            (
                role
                for role in self._store.roles.values()
                if role.organisation_id == organisation_id and role.name == name
            ),
            None,
        )

    def add_role(self, record: RoleRecord) -> None:
        if self.find_role_by_name(record.organisation_id or "", record.name) is not None:
            raise ValueError("duplicate role name")
        self._store.roles[record.id] = record

    def update_role(self, record: RoleRecord) -> None:
        self._store.roles[record.id] = record

    def list_bindings(
        self, organisation_id: str, role_id: str, *, role_is_builtin: bool = False
    ) -> list[RolePermissionRecord]:
        return [
            binding
            for binding in self._store.bindings.values()
            if binding.role_id == role_id
            and binding.organisation_id in (organisation_id, None)
        ]

    def find_binding(
        self, organisation_id: str, role_id: str, permission_name: str
    ) -> RolePermissionRecord | None:
        return next(
            (
                binding
                for binding in self._store.bindings.values()
                if binding.role_id == role_id
                and binding.permission_name == permission_name
            ),
            None,
        )

    def add_binding(self, record: RolePermissionRecord) -> None:
        if (
            self.find_binding(
                record.organisation_id, record.role_id, record.permission_name
            )
            is not None
        ):
            raise ValueError("duplicate binding")
        self._store.bindings[record.id] = record

    def remove_binding(
        self, organisation_id: str, role_id: str, permission_name: str
    ) -> None:
        existing = self.find_binding(organisation_id, role_id, permission_name)
        if existing is None:
            raise LookupError(permission_name)
        del self._store.bindings[existing.id]


class InMemoryAssignmentRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def list_assignments(
        self,
        organisation_id: str,
        *,
        user_id: str | None = None,
        role_id: str | None = None,
        include_ended: bool = False,
    ) -> list[RoleAssignmentRecord]:
        return [
            item
            for item in self._store.assignments.values()
            if item.organisation_id == organisation_id
            and (user_id is None or item.user_id == user_id)
            and (role_id is None or item.role_id == role_id)
            and (include_ended or (item.revoked_at is None))
        ]

    def get_assignment(
        self, organisation_id: str, assignment_id: str
    ) -> RoleAssignmentRecord:
        item = self._store.assignments.get(assignment_id)
        if item is None or item.organisation_id != organisation_id:
            raise LookupError(assignment_id)
        return item

    def find_assignment(
        self,
        organisation_id: str,
        user_id: str,
        role_id: str,
        scope_type: str,
        scope_id: str | None,
    ) -> RoleAssignmentRecord | None:
        return next(
            (
                item
                for item in self._store.assignments.values()
                if item.organisation_id == organisation_id
                and item.user_id == user_id
                and item.role_id == role_id
                and item.scope_type == scope_type
                and item.scope_id == scope_id
                and item.revoked_at is None
            ),
            None,
        )

    def add_assignment(self, record: RoleAssignmentRecord) -> None:
        if (
            self.find_assignment(
                record.organisation_id,
                record.user_id,
                record.role_id,
                record.scope_type,
                record.scope_id,
            )
            is not None
        ):
            raise ValueError("duplicate assignment")
        self._store.assignments[record.id] = record

    def update_assignment(self, record: RoleAssignmentRecord) -> None:
        self._store.assignments[record.id] = record


class InMemoryUnitOfWork:
    """A transaction over the in-memory store."""

    def __init__(self, store: InMemoryStore, *, fail_audit: bool = False) -> None:
        self._store = store
        self._snapshot: dict[str, Any] | None = None
        self.agents = InMemoryRegistryRepository(store)
        self.approvals = InMemoryApprovalRepository(store)
        self.users = InMemoryUserRepository(store)
        self.permissions = InMemoryPermissionRepository(store)
        self.assignments = InMemoryAssignmentRepository(store)
        self.audit = InMemoryAudit(store, fail=fail_audit)
        self.events = InMemoryEvents(store)

    def __enter__(self) -> InMemoryUnitOfWork:
        self._snapshot = deepcopy(self._store.__dict__)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None and self._snapshot is not None:
            self._store.__dict__.clear()
            self._store.__dict__.update(self._snapshot)
        return None


class InMemoryAuthorizationEngine:
    """A stand-in for the policy engine.

    It mirrors the RBAC and accountability rules of
    `deploy/policy/authorization.rego`, because the engine itself is not
    installed in every environment. It doubles the *external service*, never the
    code under test; the real bundle is covered by `opa test`.

    `fail=True` simulates an unreachable engine, which is what the fail-closed
    tests need.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.seen: list[dict[str, Any]] = []

    async def decide(self, decision_input: Any) -> AuthorizationDecision:
        document = dict(decision_input)
        self.seen.append(document)
        if self._fail:
            raise DecisionUnavailable("policy engine unreachable")

        permissions = document.get("permissions", [])
        # The accountability rule and its exemption, mirroring the bundle: the
        # holder of `registry.write_any` may act on another person's resource.
        if (
            document.get("requires_resource_accountability")
            and REGISTRY_WRITE_ANY not in permissions
        ):
            resource = document.get("resource")
            if resource is None:
                return AuthorizationDecision(
                    allowed=False,
                    reason="denied by ['abac.resource_missing']",
                    sources=("abac.resource_missing",),
                )
            if resource.get("owner_user_id") != document.get("user_id"):
                return AuthorizationDecision(
                    allowed=False,
                    reason="denied by ['abac.resource_accountability']",
                    sources=("abac.resource_accountability",),
                )

        if document.get("permission") in permissions:
            return AuthorizationDecision(
                allowed=True,
                reason="granted by ['rbac.permission_granted']",
                sources=("rbac.permission_granted",),
            )
        return AuthorizationDecision(
            allowed=False,
            reason="deny by default: no rule grants this action",
        )


def seed_builtin_roles(store: InMemoryStore) -> dict[str, RoleRecord]:
    """Create the five built-in roles with the permissions the matrix gives them.

    Built-in roles have no organisation, which is also how the domain identifies
    them as immutable.
    """
    roles: dict[str, RoleRecord] = {}
    for code in sorted(ROLES):
        role_id = f"builtin-{code}"
        store.roles[role_id] = RoleRecord(
            id=role_id,
            organisation_id=None,
            code=code,
            name=code.replace("_", " ").title(),
            description=f"The platform's {code} role.",
        )
        for index, permission in enumerate(sorted(ROLE_PERMISSIONS[code])):
            binding_id = f"builtin-{code}-{index}"
            store.bindings[binding_id] = RolePermissionRecord(
                id=binding_id,
                organisation_id=None,
                role_id=role_id,
                permission_name=permission,
                granted_by="system",
                granted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        roles[code] = store.roles[role_id]
    return roles


def assign_builtin_role(
    store: InMemoryStore, *, organisation_id: str, user_id: str, code: str
) -> RoleAssignmentRecord:
    """Assign one built-in role to a user, as a deployment's identity does."""
    record = RoleAssignmentRecord(
        id=f"builtin-assignment-{code}",
        organisation_id=organisation_id,
        user_id=user_id,
        role_id=f"builtin-{code}",
        scope_type="organisation",
        granted_by="system",
        granted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.assignments[record.id] = record
    return record
