"""Unit tests for permission-change recording (T013, FR-021, FR-022)."""

from __future__ import annotations

import pytest
from _inmemory import InMemoryAudit, InMemoryEvents, InMemoryStore

from gov.api.application.permission.audit import (
    ASSIGNMENT_REVOKED,
    PERMISSION_BOUND,
    PERMISSION_CHANGE_EVENT,
    RESPONSIBILITY_TRANSFERRED,
    ROLE_CREATED,
    ROLE_RETIRED,
    USER_DISABLED,
    USER_ENABLED,
    PermissionChange,
    PermissionChangeError,
    PermissionChangeRecorder,
)

ORG = "org-1"
ACTOR = "admin-1"


def _recorder(*, fail_audit: bool = False) -> tuple[PermissionChangeRecorder, InMemoryStore]:
    store = InMemoryStore()
    recorder = PermissionChangeRecorder(
        audit=InMemoryAudit(store, fail=fail_audit), events=InMemoryEvents(store)
    )
    return recorder, store


def _change(**overrides: object) -> PermissionChange:
    payload: dict[str, object] = {
        "organisation_id": ORG,
        "actor": ACTOR,
        "action": ROLE_CREATED,
        "target_type": "role",
        "target_id": "role-1",
    }
    payload.update(overrides)
    return PermissionChange(**payload)  # type: ignore[arg-type]


def test_a_change_is_recorded_with_its_actor_target_and_action() -> None:
    recorder, store = _recorder()
    entry = recorder.record(_change(detail={"name": "erp-invoice-owner"}))

    assert entry.actor == ACTOR
    assert entry.action == ROLE_CREATED
    assert entry.target_type == "role"
    assert entry.target_id == "role-1"
    assert entry.outcome == "success"
    assert entry.detail == {"name": "erp-invoice-owner"}
    assert store.audit == [entry]


def test_a_change_also_publishes_a_domain_event() -> None:
    recorder, store = _recorder()
    recorder.record(_change())

    assert len(store.events) == 1
    assert store.events[0].event_type == PERMISSION_CHANGE_EVENT
    assert store.events[0].aggregate_id == "role-1"
    assert store.events[0].payload["action"] == ROLE_CREATED


@pytest.mark.parametrize(
    "action",
    [ROLE_RETIRED, ASSIGNMENT_REVOKED, RESPONSIBILITY_TRANSFERRED, USER_DISABLED],
)
def test_a_reason_is_required_where_it_explains_the_change(action: str) -> None:
    recorder, store = _recorder()
    with pytest.raises(PermissionChangeError) as excinfo:
        recorder.record(_change(action=action))

    assert excinfo.value.code == "reason_required"
    assert store.audit == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_blank_reason_is_not_a_reason(reason: str | None) -> None:
    recorder, _ = _recorder()
    with pytest.raises(PermissionChangeError):
        recorder.record(_change(action=ASSIGNMENT_REVOKED, reason=reason))


def test_a_reasoned_change_is_recorded_with_its_reason() -> None:
    recorder, store = _recorder()
    recorder.record(
        _change(
            action=ASSIGNMENT_REVOKED,
            target_type="role_assignment",
            reason="the developer left the team",
        )
    )
    assert store.audit[-1].reason == "the developer left the team"


def test_an_ordinary_change_does_not_need_a_reason() -> None:
    recorder, _ = _recorder()
    recorder.record(_change(action=PERMISSION_BOUND, detail={"permission": "registry.read"}))
    recorder.record(_change(action=USER_ENABLED, target_type="user", target_id="user-2"))


def test_a_failing_audit_write_propagates_so_the_change_rolls_back() -> None:
    """A change that happened without its record is worse than no change."""
    recorder, store = _recorder(fail_audit=True)
    with pytest.raises(RuntimeError):
        recorder.record(_change())
    assert store.events == []


def test_recording_without_an_event_port_still_writes_the_record() -> None:
    store = InMemoryStore()
    recorder = PermissionChangeRecorder(audit=InMemoryAudit(store))
    recorder.record(_change())
    assert len(store.audit) == 1
    assert store.events == []
