"""Unit tests for the registry use cases (T041, US1)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest
from _inmemory import InMemoryStore, InMemoryUnitOfWork

from gov.api.application.ports import ConflictError, NotFoundError
from gov.api.application.registry.service import RegistryService
from gov.api.domain.classification import PUBLIC
from gov.api.domain.registry.entities import DomainValidationError, ToolPermission

ORG = "org-1"
ACTOR = "user-1"
CLOCK = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _service(
    *, fail_audit: bool = False
) -> tuple[RegistryService, InMemoryStore]:
    store = InMemoryStore()
    counter = itertools.count(1)
    service = RegistryService(
        lambda: InMemoryUnitOfWork(store, fail_audit=fail_audit),
        clock=lambda: CLOCK,
        new_id=lambda: f"id-{next(counter)}",
    )
    return service, store


def _permission() -> ToolPermission:
    return ToolPermission(
        resource_type="erp.invoice", action="read", data_class=PUBLIC
    )


# ------------------------------------------------------------------- agents


def test_creating_an_agent_persists_it_and_records_one_audit_and_one_event() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )

    assert store.agents[agent.id].name == "ap-reconciler"
    assert len(store.audit) == 1
    assert len(store.events) == 1
    assert store.audit[0].action == "create"
    assert store.audit[0].target_type == "agent"
    assert store.audit[0].outcome == "success"
    assert store.events[0].event_type == "agent.registered"


def test_a_duplicate_agent_name_is_refused_and_changes_nothing() -> None:
    service, store = _service()
    service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    with pytest.raises(ConflictError):
        service.create_agent(
            organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
        )

    assert len(store.agents) == 1
    assert len(store.audit) == 1
    assert len(store.events) == 1


def test_an_agent_without_an_owner_creates_no_record_at_all() -> None:
    """US1 scenario 4: nothing is written for an incomplete submission."""
    service, store = _service()
    with pytest.raises(DomainValidationError) as excinfo:
        service.create_agent(
            organisation_id=ORG, name="ap-reconciler", owner_user_id="", actor=ACTOR
        )

    assert excinfo.value.field == "owner_user_id"
    assert store.agents == {}
    assert store.audit == []
    assert store.events == []


def test_the_same_name_may_be_used_in_another_organisation() -> None:
    service, store = _service()
    service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    service.create_agent(
        organisation_id="org-2",
        name="ap-reconciler",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )
    assert len(store.agents) == 2


def test_updating_an_agent_records_the_change() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    updated = service.update_agent(
        organisation_id=ORG, agent_id=agent.id, actor=ACTOR, owner_user_id="user-2"
    )
    assert updated.owner_user_id == "user-2"
    assert store.audit[-1].action == "update"


def test_retiring_an_agent_records_the_previous_status() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    retired = service.retire_agent(
        organisation_id=ORG, agent_id=agent.id, actor=ACTOR
    )
    assert retired.status == "retired"
    assert store.audit[-1].detail["previous_status"] == "draft"


def test_operating_on_an_unknown_agent_is_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        service.add_version(
            organisation_id=ORG,
            agent_id="missing",
            version="1.0.0",
            owner_user_id=ACTOR,
            actor=ACTOR,
        )


# ----------------------------------------------------------------- versions


def test_adding_a_version_persists_it() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    version = service.add_version(
        organisation_id=ORG,
        agent_id=agent.id,
        version="1.0.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )
    assert store.versions[version.id].version == "1.0.0"
    assert store.audit[-1].action == "create_version"


def test_a_duplicate_version_is_refused() -> None:
    service, _ = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    service.add_version(
        organisation_id=ORG,
        agent_id=agent.id,
        version="1.0.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )
    with pytest.raises(ConflictError):
        service.add_version(
            organisation_id=ORG,
            agent_id=agent.id,
            version="1.0.0",
            owner_user_id=ACTOR,
            actor=ACTOR,
        )


def test_a_malformed_version_is_rejected_before_anything_is_written() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    with pytest.raises(DomainValidationError):
        service.add_version(
            organisation_id=ORG,
            agent_id=agent.id,
            version="not-a-version",
            owner_user_id=ACTOR,
            actor=ACTOR,
        )
    assert store.versions == {}


def test_releasing_a_version_demotes_the_previous_one() -> None:
    """FR-006: at most one released version per agent."""
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    first = service.add_version(
        organisation_id=ORG,
        agent_id=agent.id,
        version="1.0.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )
    second = service.add_version(
        organisation_id=ORG,
        agent_id=agent.id,
        version="1.1.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )

    service.release_version(
        organisation_id=ORG, agent_id=agent.id, version="1.0.0", actor=ACTOR
    )
    assert store.versions[first.id].status == "released"
    assert store.agents[agent.id].status == "active"

    service.release_version(
        organisation_id=ORG, agent_id=agent.id, version="1.1.0", actor=ACTOR
    )
    assert store.versions[second.id].status == "released"
    assert store.versions[first.id].status == "deprecated"
    assert store.audit[-1].detail["demoted"] == "1.0.0"
    assert store.versions[second.id].released_at == CLOCK


def test_releasing_an_unknown_version_is_not_found() -> None:
    service, _ = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    with pytest.raises(NotFoundError):
        service.release_version(
            organisation_id=ORG, agent_id=agent.id, version="9.9.9", actor=ACTOR
        )


# -------------------------------------------------------------------- tools


def test_creating_a_tool_persists_permissions_and_emits_a_tool_event() -> None:
    service, store = _service()
    tool = service.create_tool(
        organisation_id=ORG,
        name="invoice-reader",
        risk_level="low",
        risk_basis="read-only, non-sensitive metadata",
        adapter_ref="erp.invoice.read",
        permissions=[_permission()],
        actor=ACTOR,
    )
    assert store.tools[tool.id].permissions == (_permission(),)
    assert store.events[-1].event_type == "tool.registered"


def test_a_tool_without_permissions_is_refused_and_writes_nothing() -> None:
    service, store = _service()
    with pytest.raises(DomainValidationError) as excinfo:
        service.create_tool(
            organisation_id=ORG,
            name="invoice-reader",
            risk_level="low",
            risk_basis="read-only",
            adapter_ref="erp.invoice.read",
            permissions=[],
            actor=ACTOR,
        )
    assert excinfo.value.field == "permissions"
    assert store.tools == {}
    assert store.audit == []


def test_a_duplicate_tool_name_is_refused() -> None:
    service, _ = _service()
    service.create_tool(
        organisation_id=ORG,
        name="invoice-reader",
        risk_level="low",
        risk_basis="read-only",
        adapter_ref="erp.invoice.read",
        permissions=[_permission()],
        actor=ACTOR,
    )
    with pytest.raises(ConflictError):
        service.create_tool(
            organisation_id=ORG,
            name="invoice-reader",
            risk_level="low",
            risk_basis="read-only",
            adapter_ref="erp.invoice.read",
            permissions=[_permission()],
            actor=ACTOR,
        )


def test_raising_a_tool_risk_level_is_recorded_with_the_change() -> None:
    """FR-010: a risk change is recorded, not applied silently."""
    service, store = _service()
    tool = service.create_tool(
        organisation_id=ORG,
        name="payment-writer",
        risk_level="medium",
        risk_basis="writes payment instructions",
        adapter_ref="fin.payment.write",
        permissions=[_permission()],
        actor=ACTOR,
    )
    service.update_tool(
        organisation_id=ORG,
        tool_id=tool.id,
        actor=ACTOR,
        risk_level="high",
        risk_basis="writes payment instructions to the ledger",
    )
    assert store.tools[tool.id].risk_level == "high"
    assert store.audit[-1].detail == {
        "previous_risk_level": "medium",
        "risk_level": "high",
    }


def test_an_invalid_risk_level_is_refused_and_leaves_the_tool_unchanged() -> None:
    service, store = _service()
    tool = service.create_tool(
        organisation_id=ORG,
        name="payment-writer",
        risk_level="medium",
        risk_basis="writes payment instructions",
        adapter_ref="fin.payment.write",
        permissions=[_permission()],
        actor=ACTOR,
    )
    with pytest.raises(DomainValidationError):
        service.update_tool(
            organisation_id=ORG, tool_id=tool.id, actor=ACTOR, risk_level="catastrophic"
        )
    assert store.tools[tool.id].risk_level == "medium"


def test_updating_a_missing_tool_is_not_found() -> None:
    service, _ = _service()
    with pytest.raises(NotFoundError):
        service.update_tool(
            organisation_id=ORG, tool_id="missing", actor=ACTOR, risk_level="high"
        )


# ---------------------------------------------------------------- integrity


def test_a_failing_audit_write_rolls_the_mutation_back() -> None:
    """The change and its audit record cannot be separated."""
    service, store = _service(fail_audit=True)
    with pytest.raises(RuntimeError):
        service.create_agent(
            organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
        )

    assert store.agents == {}
    assert store.audit == []
    assert store.events == []


def test_every_successful_mutation_emits_exactly_one_audit_and_one_event() -> None:
    service, store = _service()
    agent = service.create_agent(
        organisation_id=ORG, name="ap-reconciler", owner_user_id=ACTOR, actor=ACTOR
    )
    service.add_version(
        organisation_id=ORG,
        agent_id=agent.id,
        version="1.0.0",
        owner_user_id=ACTOR,
        actor=ACTOR,
    )
    service.release_version(
        organisation_id=ORG, agent_id=agent.id, version="1.0.0", actor=ACTOR
    )
    service.create_tool(
        organisation_id=ORG,
        name="invoice-reader",
        risk_level="low",
        risk_basis="read-only",
        adapter_ref="erp.invoice.read",
        permissions=[_permission()],
        actor=ACTOR,
    )
    service.update_agent(
        organisation_id=ORG, agent_id=agent.id, actor=ACTOR, description="reconciles AP"
    )
    service.retire_agent(organisation_id=ORG, agent_id=agent.id, actor=ACTOR)

    assert len(store.audit) == 6
    assert len(store.events) == 6
    assert all(entry.outcome == "success" for entry in store.audit)
    assert all(entry.actor == ACTOR for entry in store.audit)
