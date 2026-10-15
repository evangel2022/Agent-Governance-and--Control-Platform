"""Accountability for an Agent.

There is no responsibility table. The Agent Registry already records the
accountable person as `agent.owner_user_id`, `NOT NULL` and already keyed to a
user in the same organisation, so a second table naming the same person would be
a second answer to "who is accountable" - and the two would drift.

What is left for the domain is the *transfer*: it must be explained, it must go
to somebody, and it must actually change something. Each of those is a rule
rather than a formality, so each is checked here.
"""

from __future__ import annotations

from gov.api.domain.permission.rules import PermissionRuleError


def validate_transfer(
    *,
    current_owner_user_id: str | None,
    new_owner_user_id: str | None,
    reason: str | None,
) -> None:
    """Check a transfer of accountability before it is applied.

    Raises:
        PermissionRuleError: when the new owner is missing, when no reason is
            given, or when the transfer would change nothing.
    """
    if new_owner_user_id is None or not new_owner_user_id.strip():
        raise PermissionRuleError(
            "owner_required", "an Agent must have an accountable person"
        )
    if reason is None or not reason.strip():
        raise PermissionRuleError(
            "reason_required",
            "a transfer requires a reason, because it is the only thing that "
            "explains later why accountability moved",
        )
    if current_owner_user_id == new_owner_user_id:
        raise PermissionRuleError(
            "no_change",
            "accountability already rests with this person; a transfer must "
            "move it",
        )


def is_accountable(*, owner_user_id: str | None, user_id: str) -> bool:
    """Whether a user is the person accountable for an Agent."""
    return owner_user_id is not None and owner_user_id == user_id
