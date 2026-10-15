"""Effective permission resolution.

Answers one question the request path asks on every protected call: what may this
person do, in this organisation, right now? The answer is the union of the
permissions of every role they hold through an assignment that is still
effective - not revoked, not expired - restricted to roles that are still active,
and to permission names the catalogue recognises.

Two design points carry the acceptance criteria:

* **Unknown names grant nothing.** A binding whose name is not in the catalogue
  is ignored rather than trusted, which is FR-008 applied where it matters.
* **Invalidation is exact, not timed.** The cache is keyed by a per-organisation
  generation that every role, binding and assignment change bumps. That is what
  lets a revocation take effect at the next verification (FR-020) instead of at
  the end of a TTL. The TTL is only a backstop for changes made by another process,
  which this in-process cache cannot see; a shared cache arrives with Redis.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gov.api.application.ports import UnitOfWork
from gov.api.domain.permission.catalogue import BY_NAME
from gov.api.domain.permission.rules import RoleStatus, is_effective

DEFAULT_TTL = timedelta(seconds=30)


@dataclass
class EffectivePermissionCache:
    """Per-process cache of effective permission sets."""

    ttl: timedelta = DEFAULT_TTL
    _generation: dict[str, int] = field(default_factory=dict)
    _entries: dict[tuple[str, str], tuple[int, datetime, frozenset[str]]] = field(
        default_factory=dict
    )

    def generation(self, organisation_id: str) -> int:
        """The current generation for an organisation."""
        return self._generation.get(organisation_id, 0)

    def bump(self, organisation_id: str) -> int:
        """Invalidate every cached set for an organisation.

        Called by every use case that changes a role, a binding or an assignment,
        so a stale grant cannot survive the change that ended it.
        """
        next_generation = self.generation(organisation_id) + 1
        self._generation[organisation_id] = next_generation
        stale = [key for key in self._entries if key[0] == organisation_id]
        for key in stale:
            del self._entries[key]
        return next_generation

    def get(
        self, organisation_id: str, user_id: str, *, at: datetime
    ) -> frozenset[str] | None:
        """Return a cached set, or None when it is absent or stale."""
        entry = self._entries.get((organisation_id, user_id))
        if entry is None:
            return None
        generation, stamped_at, permissions = entry
        if generation != self.generation(organisation_id):
            return None
        if at - stamped_at > self.ttl:
            return None
        return permissions

    def put(
        self,
        organisation_id: str,
        user_id: str,
        permissions: frozenset[str],
        *,
        at: datetime,
    ) -> None:
        """Record a resolved set against the current generation."""
        self._entries[(organisation_id, user_id)] = (
            self.generation(organisation_id),
            at,
            permissions,
        )

    def clear(self) -> None:
        """Drop every entry. Used by tests and by a process restart."""
        self._entries.clear()


class EffectivePermissionResolver:
    """Resolves and caches effective permissions."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime],
        cache: EffectivePermissionCache | None = None,
    ) -> None:
        self._uow = uow_factory
        self._clock = clock
        self._cache = cache if cache is not None else EffectivePermissionCache()

    @property
    def cache(self) -> EffectivePermissionCache:
        return self._cache

    def invalidate(self, organisation_id: str) -> None:
        """Invalidate an organisation's cached sets after a change."""
        self._cache.bump(organisation_id)

    def resolve(
        self,
        *,
        organisation_id: str,
        user_id: str,
        at: datetime | None = None,
    ) -> frozenset[str]:
        """Return what this person may do, in this organisation, at this moment.

        An unknown or disabled user gets nothing rather than an error: this runs
        on the authorization path, where the safe answer to "who is this?" is
        "nobody", not an exception.
        """
        moment = at if at is not None else self._clock()

        cached = self._cache.get(organisation_id, user_id, at=moment)
        if cached is not None:
            return cached

        granted: set[str] = set()
        with self._uow() as uow:
            try:
                user = uow.users.get_user(organisation_id, user_id)
            except LookupError:
                return frozenset()
            if user.status != "active":
                return frozenset()

            for assignment in uow.assignments.list_assignments(
                organisation_id, user_id=user.id
            ):
                if not is_effective(
                    revoked_at=assignment.revoked_at,
                    expires_at=assignment.expires_at,
                    at=moment,
                ):
                    continue
                try:
                    role = uow.permissions.get_role(organisation_id, assignment.role_id)
                except LookupError:
                    continue
                if role.status != RoleStatus.ACTIVE.value:
                    continue
                for binding in uow.permissions.list_bindings(
                    organisation_id, role.id, role_is_builtin=role.is_builtin
                ):
                    if binding.permission_name in BY_NAME:
                        granted.add(binding.permission_name)

        resolved = frozenset(granted)
        self._cache.put(organisation_id, user_id, resolved, at=moment)
        return resolved
