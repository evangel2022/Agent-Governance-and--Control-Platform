"""Registry use cases: register, version, update and retire Agents and Tools.

Implements FR-005 to FR-010 (US1). Two invariants are enforced here rather than
left to the adapter:

1. **Validation happens before the transaction opens.** An incomplete submission
   therefore cannot create a partial record, because there is nothing to roll
   back (US1 scenario 4).
2. **Audit and event emission happen inside the transaction.** If either fails,
   the mutation is rolled back, so a state change can never exist without its
   audit record (constitution Principle III, ADR-0007).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from gov.api.application.ports import (
    AgentRecord,
    AgentVersionRecord,
    AuditEntry,
    ConflictError,
    DomainEvent,
    NotFoundError,
    ToolRecord,
    UnitOfWork,
)
from gov.api.domain.registry.entities import (
    Agent,
    AgentVersion,
    Tool,
    ToolPermission,
)

AGENT_EVENT = "agent.registered"
TOOL_EVENT = "tool.registered"


class RegistryService:
    """Registry use cases over a unit of work."""

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

    # ------------------------------------------------------------------ agents

    def get_agent(self, *, organisation_id: str, agent_id: str) -> AgentRecord:
        """Return one Agent.

        Raises:
            NotFoundError: when the Agent does not exist in this organisation.
        """
        with self._uow() as uow:
            return self._require_agent(uow, organisation_id, agent_id)

    def list_agents(
        self,
        *,
        organisation_id: str,
        status: str | None = None,
        owner_user_id: str | None = None,
    ) -> Sequence[AgentRecord]:
        """List Agents, optionally filtered by lifecycle status or owner."""
        with self._uow() as uow:
            return list(
                uow.agents.list_agents(
                    organisation_id, status=status, owner_user_id=owner_user_id
                )
            )

    def create_agent(
        self,
        *,
        organisation_id: str,
        name: str,
        owner_user_id: str,
        actor: str,
        description: str | None = None,
    ) -> AgentRecord:
        """Register an Agent.

        Raises:
            DomainValidationError: when the submission is incomplete.
            ConflictError: when an Agent with this name already exists.
        """
        Agent(name=name, owner_user_id=owner_user_id, description=description)

        now = self._clock()
        with self._uow() as uow:
            if uow.agents.find_agent_by_name(organisation_id, name) is not None:
                raise ConflictError(f"an agent named {name!r} already exists")

            record = AgentRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                name=name,
                owner_user_id=owner_user_id,
                created_at=now,
                updated_at=now,
                description=description,
            )
            uow.agents.add_agent(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="create",
                target_type="agent",
                target_id=record.id,
                event_type=AGENT_EVENT,
                detail={"name": name, "owner_user_id": owner_user_id},
            )
        return record

    def update_agent(
        self,
        *,
        organisation_id: str,
        agent_id: str,
        actor: str,
        description: str | None = None,
        owner_user_id: str | None = None,
    ) -> AgentRecord:
        """Update an Agent's mutable attributes."""
        with self._uow() as uow:
            record = self._require_agent(uow, organisation_id, agent_id)
            if owner_user_id is not None:
                Agent(name=record.name, owner_user_id=owner_user_id)
                record.owner_user_id = owner_user_id
            if description is not None:
                Agent(name=record.name, owner_user_id=record.owner_user_id, description=description)
                record.description = description
            record.updated_at = self._clock()
            uow.agents.update_agent(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="update",
                target_type="agent",
                target_id=record.id,
                event_type=AGENT_EVENT,
            )
        return record

    def retire_agent(
        self, *, organisation_id: str, agent_id: str, actor: str
    ) -> AgentRecord:
        """Retire an Agent so it can no longer be released or invoked."""
        with self._uow() as uow:
            record = self._require_agent(uow, organisation_id, agent_id)
            previous = record.status
            record.status = "retired"
            record.updated_at = self._clock()
            uow.agents.update_agent(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="retire",
                target_type="agent",
                target_id=record.id,
                event_type=AGENT_EVENT,
                detail={"previous_status": previous},
            )
        return record

    # ---------------------------------------------------------------- versions

    def list_versions(
        self, *, organisation_id: str, agent_id: str
    ) -> Sequence[AgentVersionRecord]:
        """List an Agent's versions.

        Raises:
            NotFoundError: when the Agent does not exist in this organisation.
        """
        with self._uow() as uow:
            self._require_agent(uow, organisation_id, agent_id)
            return list(uow.agents.list_versions(organisation_id, agent_id))

    def add_version(
        self,
        *,
        organisation_id: str,
        agent_id: str,
        version: str,
        owner_user_id: str,
        actor: str,
        model_id: str | None = None,
    ) -> AgentVersionRecord:
        """Add a version to an Agent.

        Raises:
            NotFoundError: when the Agent does not exist in this organisation.
            ConflictError: when the version already exists for this Agent.
        """
        AgentVersion(agent_id=agent_id, version=version, owner_user_id=owner_user_id)

        now = self._clock()
        with self._uow() as uow:
            self._require_agent(uow, organisation_id, agent_id)
            if uow.agents.find_version(organisation_id, agent_id, version) is not None:
                raise ConflictError(
                    f"agent version {version!r} already exists for this agent"
                )

            record = AgentVersionRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                agent_id=agent_id,
                version=version,
                owner_user_id=owner_user_id,
                created_at=now,
                updated_at=now,
                model_id=model_id,
            )
            uow.agents.add_version(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="create_version",
                target_type="agent_version",
                target_id=record.id,
                event_type=AGENT_EVENT,
                detail={"agent_id": agent_id, "version": version},
            )
        return record

    def release_version(
        self,
        *,
        organisation_id: str,
        agent_id: str,
        version: str,
        actor: str,
    ) -> AgentVersionRecord:
        """Make a version the Agent's released version.

        At most one version per Agent is released, so a previous released version
        is demoted in the same transaction (FR-006).
        """
        with self._uow() as uow:
            agent = self._require_agent(uow, organisation_id, agent_id)
            record = uow.agents.find_version(organisation_id, agent_id, version)
            if record is None:
                raise NotFoundError(
                    f"agent version {version!r} does not exist for this agent"
                )

            previous = uow.agents.released_version(organisation_id, agent_id)
            demoted: str | None = None
            if previous is not None and previous.id != record.id:
                previous.status = "deprecated"
                uow.agents.update_version(previous)
                demoted = previous.version

            record.status = "released"
            released_at = self._clock()
            record.released_at = released_at
            record.updated_at = released_at
            uow.agents.update_version(record)

            if agent.status in ("draft", "deprecated"):
                agent.status = "active"
            agent.active_version_id = record.id
            agent.updated_at = released_at
            uow.agents.update_agent(agent)

            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="release",
                target_type="agent_version",
                target_id=record.id,
                event_type=AGENT_EVENT,
                detail={"agent_id": agent_id, "version": version, "demoted": demoted},
            )
        return record

    # ------------------------------------------------------------------- tools

    def create_tool(
        self,
        *,
        organisation_id: str,
        name: str,
        risk_level: str,
        risk_basis: str,
        adapter_ref: str,
        permissions: Sequence[ToolPermission],
        actor: str,
        description: str | None = None,
    ) -> ToolRecord:
        """Register a Tool with its declared permissions and risk level (FR-007)."""
        Tool(
            name=name,
            risk_level=risk_level,
            risk_basis=risk_basis,
            adapter_ref=adapter_ref,
            permissions=tuple(permissions),
            description=description,
        )

        now = self._clock()
        with self._uow() as uow:
            if uow.agents.find_tool_by_name(organisation_id, name) is not None:
                raise ConflictError(f"a tool named {name!r} already exists")

            record = ToolRecord(
                id=self._new_id(),
                organisation_id=organisation_id,
                name=name,
                risk_level=risk_level,
                risk_basis=risk_basis,
                adapter_ref=adapter_ref,
                permissions=tuple(permissions),
                created_at=now,
                updated_at=now,
                description=description,
            )
            uow.agents.add_tool(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="create",
                target_type="tool",
                target_id=record.id,
                event_type=TOOL_EVENT,
                detail={"name": name, "risk_level": risk_level},
            )
        return record

    def update_tool(
        self,
        *,
        organisation_id: str,
        tool_id: str,
        actor: str,
        risk_level: str | None = None,
        risk_basis: str | None = None,
        permissions: Sequence[ToolPermission] | None = None,
        description: str | None = None,
    ) -> ToolRecord:
        """Update a Tool, recording any change to its risk level (FR-010)."""
        with self._uow() as uow:
            record = self._require_tool(uow, organisation_id, tool_id)
            previous_risk = record.risk_level
            candidate_permissions = (
                tuple(permissions) if permissions is not None else record.permissions
            )
            Tool(
                name=record.name,
                risk_level=risk_level or record.risk_level,
                risk_basis=risk_basis or record.risk_basis,
                adapter_ref=record.adapter_ref,
                permissions=candidate_permissions,
                description=description if description is not None else record.description,
                status=record.status,
            )

            if risk_level is not None:
                record.risk_level = risk_level
            if risk_basis is not None:
                record.risk_basis = risk_basis
            if permissions is not None:
                record.permissions = candidate_permissions
            if description is not None:
                record.description = description
            record.updated_at = self._clock()
            uow.agents.update_tool(record)
            self._emit(
                uow,
                organisation_id=organisation_id,
                actor=actor,
                action="update",
                target_type="tool",
                target_id=record.id,
                event_type=TOOL_EVENT,
                detail={
                    "previous_risk_level": previous_risk,
                    "risk_level": record.risk_level,
                },
            )
        return record

    # ----------------------------------------------------------------- helpers

    def _require_agent(
        self, uow: UnitOfWork, organisation_id: str, agent_id: str
    ) -> AgentRecord:
        try:
            return uow.agents.get_agent(organisation_id, agent_id)
        except LookupError as exc:
            raise NotFoundError(f"agent {agent_id!r} does not exist") from exc

    def _require_tool(
        self, uow: UnitOfWork, organisation_id: str, tool_id: str
    ) -> ToolRecord:
        try:
            return uow.agents.get_tool(organisation_id, tool_id)
        except LookupError as exc:
            raise NotFoundError(f"tool {tool_id!r} does not exist") from exc

    def _emit(
        self,
        uow: UnitOfWork,
        *,
        organisation_id: str,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(detail or {})
        uow.audit.record(
            AuditEntry(
                organisation_id=organisation_id,
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome="success",
                detail=payload,
            )
        )
        uow.events.publish(
            DomainEvent(
                event_type=event_type,
                organisation_id=organisation_id,
                aggregate_type=target_type,
                aggregate_id=target_id,
                payload=payload,
            )
        )
