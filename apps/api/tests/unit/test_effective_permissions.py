"""Unit tests for effective permission resolution and its cache (T011)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from _inmemory import InMemoryStore, InMemoryUnitOfWork

from gov.api.application.permission.effective import (
    EffectivePermissionCache,
    EffectivePermissionResolver,
)
from gov.api.application.ports import (
    RoleAssignmentRecord,
    RolePermissionRecord,
    RoleRecord,
    UserRecord,
)

ORG = "org-1"
OTHER_ORG = "org-2"
USER = "user-1"
ROLE = "role-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _store() -> InMemoryStore:
    store = InMemoryStore()
    store.users[USER] = UserRecord(
        id=USER,
        organisation_id=ORG,
        external_subject="sub-1",
        display_name="Dana Developer",
        email="dana@example.invalid",
    )
    store.roles[ROLE] = RoleRecord(
        id=ROLE,
        organisation_id=ORG,
        code=None,
        name="erp-invoice-owner",
        description="Owns ERP invoice Agents.",
    )
    store.assignments["a-1"] = RoleAssignmentRecord(
        id="a-1",
        organisation_id=ORG,
        user_id=USER,
        role_id=ROLE,
        scope_type="organisation",
        granted_by="admin-1",
        granted_at=NOW,
    )
    store.bindings["b-1"] = RolePermissionRecord(
        id="b-1",
        organisation_id=ORG,
        role_id=ROLE,
        permission_name="registry.read",
        granted_by="admin-1",
        granted_at=NOW,
    )
    store.bindings["b-2"] = RolePermissionRecord(
        id="b-2",
        organisation_id=ORG,
        role_id=ROLE,
        permission_name="registry.write",
        granted_by="admin-1",
        granted_at=NOW,
    )
    return store


def _resolver(store: InMemoryStore) -> EffectivePermissionResolver:
    return EffectivePermissionResolver(
        lambda: InMemoryUnitOfWork(store),
        clock=lambda: NOW,
        cache=EffectivePermissionCache(ttl=timedelta(seconds=30)),
    )


def _resolve(store: InMemoryStore, **overrides: object) -> frozenset[str]:
    resolver = _resolver(store)
    payload: dict[str, object] = {"organisation_id": ORG, "user_id": USER}
    payload.update(overrides)
    return resolver.resolve(**payload)  # type: ignore[arg-type]


def test_permissions_come_from_effective_assignments() -> None:
    assert _resolve(_store()) == frozenset({"registry.read", "registry.write"})


def test_a_user_with_no_assignments_holds_nothing() -> None:
    store = _store()
    store.assignments.clear()
    assert _resolve(store) == frozenset()


def test_a_revoked_assignment_grants_nothing() -> None:
    store = _store()
    store.assignments["a-1"].revoked_at = NOW - timedelta(minutes=1)
    store.assignments["a-1"].revocation_reason = "role removed"
    assert _resolve(store) == frozenset()


def test_an_expired_assignment_grants_nothing() -> None:
    store = _store()
    store.assignments["a-1"].expires_at = NOW - timedelta(seconds=1)
    assert _resolve(store) == frozenset()


def test_an_assignment_inside_its_window_still_grants() -> None:
    store = _store()
    store.assignments["a-1"].expires_at = NOW + timedelta(hours=1)
    assert _resolve(store) == frozenset({"registry.read", "registry.write"})


def test_a_retired_role_grants_nothing() -> None:
    store = _store()
    store.roles[ROLE].status = "retired"
    assert _resolve(store) == frozenset()


def test_an_unknown_permission_name_grants_nothing() -> None:
    """FR-008 applied where it matters: an unrecognised name is not trusted."""
    store = _store()
    store.bindings["b-3"] = RolePermissionRecord(
        id="b-3",
        organisation_id=ORG,
        role_id=ROLE,
        permission_name="registry.teleport",
        granted_by="admin-1",
        granted_at=NOW,
    )
    assert _resolve(store) == frozenset({"registry.read", "registry.write"})


def test_a_disabled_user_holds_nothing() -> None:
    """FR-002: disabling a user removes their effective permissions."""
    store = _store()
    store.users[USER].status = "disabled"
    assert _resolve(store) == frozenset()


def test_an_unknown_user_holds_nothing_rather_than_raising() -> None:
    assert _resolve(_store(), user_id="missing") == frozenset()


def test_another_organisations_assignment_is_invisible() -> None:
    store = _store()
    store.assignments["a-1"].organisation_id = OTHER_ORG
    assert _resolve(store) == frozenset()


def test_builtin_roles_grant_through_an_assignment() -> None:
    store = _store()
    store.roles[ROLE] = RoleRecord(
        id=ROLE,
        organisation_id=None,
        code="auditor",
        name="Auditor",
        description="Reads the audit trail.",
    )
    store.bindings["b-1"].organisation_id = None
    store.bindings["b-2"].permission_name = "audit.read"
    store.bindings["b-2"].organisation_id = None
    assert _resolve(store) == frozenset({"registry.read", "audit.read"})


# ------------------------------------------------------------------- caching


def test_a_second_resolution_is_served_from_the_cache() -> None:
    store = _store()
    resolver = _resolver(store)
    first = resolver.resolve(organisation_id=ORG, user_id=USER)

    # Change the data underneath without invalidating: the cache must still answer.
    store.bindings["b-2"].permission_name = "registry.retire"
    second = resolver.resolve(organisation_id=ORG, user_id=USER)

    assert second == first


def test_invalidation_makes_the_next_resolution_observe_the_change() -> None:
    """FR-020: a revocation takes effect at the next verification."""
    store = _store()
    resolver = _resolver(store)
    resolver.resolve(organisation_id=ORG, user_id=USER)

    store.assignments["a-1"].revoked_at = NOW
    store.assignments["a-1"].revocation_reason = "role removed"
    resolver.invalidate(ORG)

    assert resolver.resolve(organisation_id=ORG, user_id=USER) == frozenset()


def test_an_entry_expires_when_its_ttl_lapses() -> None:
    cache = EffectivePermissionCache(ttl=timedelta(seconds=5))
    cache.put(ORG, USER, frozenset({"registry.read"}), at=NOW)
    assert cache.get(ORG, USER, at=NOW + timedelta(seconds=4)) is not None
    assert cache.get(ORG, USER, at=NOW + timedelta(seconds=6)) is None


def test_bumping_one_organisation_leaves_another_cache_intact() -> None:
    cache = EffectivePermissionCache()
    cache.put(ORG, USER, frozenset({"registry.read"}), at=NOW)
    cache.put(OTHER_ORG, USER, frozenset({"audit.read"}), at=NOW)

    cache.bump(ORG)

    assert cache.get(ORG, USER, at=NOW) is None
    assert cache.get(OTHER_ORG, USER, at=NOW) == frozenset({"audit.read"})


def test_cache_clear_drops_everything() -> None:
    cache = EffectivePermissionCache()
    cache.put(ORG, USER, frozenset({"registry.read"}), at=NOW)
    cache.clear()
    assert cache.get(ORG, USER, at=NOW) is None
