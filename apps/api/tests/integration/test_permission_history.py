"""Reconstructing history from the record alone (SC-004, V10).

The question an audit asks is "who held this permission at that moment, and
why?", and the answer has to come from the recorded changes rather than from what
is true today - current state can tell you what is granted now, but only the
trail can tell you what was granted then.

The suite runs the real application service over the in-memory adapters, which
stand in for PostgreSQL here; the replay logic under test is the production one.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from _inmemory import InMemoryAudit, InMemoryStore, InMemoryUnitOfWork

from gov.api.application.audit.queries import AuditQueryService
from gov.api.application.permission.audit import (
    PERMISSION_BOUND,
    PERMISSION_UNBOUND,
    PermissionChange,
    PermissionChangeRecorder,
)
from gov.api.application.ports import RolePermissionRecord

ORG = "org-1"
ROLE = "role-1"
START = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def tick(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


def _service(store: InMemoryStore) -> AuditQueryService:
    return AuditQueryService(lambda: InMemoryUnitOfWork(store))


def _record(
    store: InMemoryStore,
    clock: _Clock,
    *,
    action: str,
    permission: str,
    actor: str,
    reason: str | None = None,
) -> None:
    PermissionChangeRecorder(
        audit=InMemoryAudit(store), events=None, clock=lambda: clock.now
    ).record(
        PermissionChange(
            organisation_id=ORG,
            actor=actor,
            action=action,
            target_type="role",
            target_id=ROLE,
            reason=reason,
            detail={"permission_name": permission},
        )
    )


#: Twenty changes across four permissions and four actors: enough history that a
#: correct replay cannot be a coincidence.
SCRIPT: tuple[tuple[str, str, str, str | None], ...] = (
    (PERMISSION_BOUND, "registry.read", "user-a", None),
    (PERMISSION_BOUND, "registry.write", "user-a", None),
    (PERMISSION_UNBOUND, "registry.read", "user-b", "narrowed the role"),
    (PERMISSION_BOUND, "policy.read", "user-b", None),
    (PERMISSION_BOUND, "audit.read", "user-c", None),
    (PERMISSION_UNBOUND, "registry.write", "user-c", "moved to read-only"),
    (PERMISSION_BOUND, "registry.read", "user-d", None),
    (PERMISSION_UNBOUND, "audit.read", "user-a", "over-broad"),
    (PERMISSION_BOUND, "registry.write", "user-d", None),
    (PERMISSION_BOUND, "audit.read", "user-b", None),
    (PERMISSION_UNBOUND, "policy.read", "user-a", "unused"),
    (PERMISSION_BOUND, "policy.read", "user-c", None),
    (PERMISSION_UNBOUND, "registry.read", "user-b", "duplicate path"),
    (PERMISSION_BOUND, "registry.read", "user-c", None),
    (PERMISSION_UNBOUND, "registry.write", "user-d", "narrowed"),
    (PERMISSION_BOUND, "registry.write", "user-a", None),
    (PERMISSION_BOUND, "audit.read", "user-b", None),
    (PERMISSION_UNBOUND, "policy.read", "user-a", "unused again"),
    (PERMISSION_BOUND, "policy.read", "user-d", None),
    (PERMISSION_UNBOUND, "audit.read", "user-c", "review complete"),
)


def _build_history(
    store: InMemoryStore, clock: _Clock
) -> list[tuple[datetime, frozenset[str], str, str, str | None]]:
    """Apply the script and return the expected answer at each moment."""
    current: set[str] = set()
    moments: list[tuple[datetime, frozenset[str], str, str, str | None]] = []
    for action, permission, actor, reason in SCRIPT:
        clock.tick(minutes=7)
        _record(
            store,
            clock,
            action=action,
            permission=permission,
            actor=actor,
            reason=reason,
        )
        if action == PERMISSION_BOUND:
            current.add(permission)
        else:
            current.discard(permission)
        moments.append((clock.now, frozenset(current), actor, permission, reason))
    return moments


def test_sc004_who_held_a_permission_at_twenty_past_moments() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    moments = _build_history(store, clock)
    service = _service(store)

    assert len(moments) == 20
    for moment, expected, actor, permission, reason in moments:
        state = service.permissions_at(organisation_id=ORG, role_id=ROLE, at=moment)
        assert state.permissions == expected, f"wrong set at {moment.isoformat()}"
        # The evidence for the newest change is the change itself: its actor, what
        # it did, and (for a removal) why.
        latest = state.sources[-1]
        assert latest.actor == actor
        assert latest.action in {PERMISSION_BOUND, PERMISSION_UNBOUND}
        assert latest.detail["permission_name"] == permission
        assert latest.reason == reason


def test_sc004_the_answer_changes_with_the_moment_not_just_the_present() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    moments = _build_history(store, clock)
    service = _service(store)

    first = service.permissions_at(organisation_id=ORG, role_id=ROLE, at=moments[0][0])
    last = service.permissions_at(organisation_id=ORG, role_id=ROLE, at=moments[-1][0])

    assert first.permissions != last.permissions
    assert first.permissions == moments[0][1]
    assert last.permissions == moments[-1][1]


def test_sc004_current_state_alone_is_not_evidence() -> None:
    """A grant that was never recorded is not part of the replayed history.

    This is the property that separates a reconstruction from a status report:
    the trail is the source, so an unrecorded binding grants nothing here even
    though the binding table would show it.
    """
    store = InMemoryStore()
    store.bindings["ghost"] = RolePermissionRecord(
        id="ghost",
        organisation_id=ORG,
        role_id=ROLE,
        permission_name="registry.read",
        granted_by="nobody",
        granted_at=START,
    )
    service = _service(store)

    state = service.permissions_at(organisation_id=ORG, role_id=ROLE, at=START)

    assert state.permissions == frozenset()
    assert state.sources == ()


def test_sc004_a_moment_before_the_first_change_grants_nothing() -> None:
    store = InMemoryStore()
    clock = _Clock(START)
    moments = _build_history(store, clock)
    service = _service(store)

    state = service.permissions_at(
        organisation_id=ORG, role_id=ROLE, at=moments[0][0] - timedelta(seconds=1)
    )

    assert state.permissions == frozenset()
