"""Unit tests for the release lifecycle state machine (T082, US6)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from gov.api.domain.release.state import (
    Release,
    ReleaseError,
    ReleaseState,
)

AT = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _release(**overrides: object) -> Release:
    payload: dict[str, object] = {
        "id": "rel-1",
        "organisation_id": "org-1",
        "agent_id": "agent-1",
        "agent_version_id": "agent-version-1",
    }
    payload.update(overrides)
    return Release(**payload)  # type: ignore[arg-type]


def test_a_new_release_is_active_and_serves_traffic() -> None:
    release = _release()
    assert release.state is ReleaseState.RELEASED
    assert release.is_active is True
    assert release.is_terminal is False
    assert release.events == []


def test_canary_records_the_share_and_the_event() -> None:
    release = _release()
    event = release.start_canary(percent=10, actor_id="user-1", at=AT)
    assert release.state is ReleaseState.CANARY
    assert release.canary_percent == 10
    assert event.from_state == "released"
    assert event.to_state == "canary"
    assert event.actor_id == "user-1"


@pytest.mark.parametrize("percent", [0, -1, 100, 101])
def test_canary_share_must_be_partial(percent: int) -> None:
    release = _release()
    with pytest.raises(ReleaseError) as excinfo:
        release.start_canary(percent=percent, actor_id="user-1", at=AT)
    assert excinfo.value.code == "invalid_percent"
    assert release.state is ReleaseState.RELEASED


def test_canary_cannot_start_twice() -> None:
    release = _release()
    release.start_canary(percent=10, actor_id="user-1", at=AT)
    with pytest.raises(ReleaseError) as excinfo:
        release.start_canary(percent=20, actor_id="user-1", at=AT)
    assert excinfo.value.code == "invalid_state"


def test_promotion_completes_the_rollout() -> None:
    release = _release()
    release.start_canary(percent=10, actor_id="user-1", at=AT)
    event = release.promote(actor_id="user-1", at=AT)
    assert release.state is ReleaseState.PROMOTED
    assert release.canary_percent is None
    assert event.from_state == "canary"
    assert release.is_active is True


def test_a_release_that_never_became_a_canary_cannot_be_promoted() -> None:
    release = _release()
    with pytest.raises(ReleaseError) as excinfo:
        release.promote(actor_id="user-1", at=AT)
    assert excinfo.value.code == "invalid_state"


@pytest.mark.parametrize("state", [ReleaseState.CANARY, ReleaseState.PROMOTED])
def test_rollback_returns_to_the_previous_release(state: ReleaseState) -> None:
    release = _release(previous_release_id="rel-0")
    if state is ReleaseState.CANARY:
        release.start_canary(percent=10, actor_id="user-1", at=AT)
    else:
        release.start_canary(percent=10, actor_id="user-1", at=AT)
        release.promote(actor_id="user-1", at=AT)

    event = release.rollback(
        reason="elevated tool error rate in the canary window",
        actor_id="user-1",
        at=AT,
    )
    assert release.state is ReleaseState.ROLLED_BACK
    assert release.is_active is False
    assert event.reason is not None and "error rate" in event.reason


def test_rollback_requires_a_reason() -> None:
    release = _release(previous_release_id="rel-0")
    release.start_canary(percent=10, actor_id="user-1", at=AT)
    with pytest.raises(ReleaseError) as excinfo:
        release.rollback(reason="   ", actor_id="user-1", at=AT)
    assert excinfo.value.code == "reason_required"
    assert release.state is ReleaseState.CANARY


def test_rollback_without_a_previous_release_is_refused() -> None:
    release = _release()
    release.start_canary(percent=10, actor_id="user-1", at=AT)
    with pytest.raises(ReleaseError) as excinfo:
        release.rollback(reason="bad rollout", actor_id="user-1", at=AT)
    assert excinfo.value.code == "no_previous_release"


def test_a_rolled_back_release_cannot_be_rolled_back_again() -> None:
    release = _release(previous_release_id="rel-0")
    release.start_canary(percent=10, actor_id="user-1", at=AT)
    release.rollback(reason="bad rollout", actor_id="user-1", at=AT)
    with pytest.raises(ReleaseError) as excinfo:
        release.rollback(reason="again", actor_id="user-1", at=AT)
    assert excinfo.value.code == "invalid_state"


def test_decommission_is_terminal_and_requires_a_reason() -> None:
    release = _release()
    event = release.decommission(
        reason="superseded by agent-version-2", actor_id="user-1", at=AT
    )
    assert release.state is ReleaseState.DECOMMISSIONED
    assert release.is_terminal is True
    assert release.is_active is False
    assert event.reason == "superseded by agent-version-2"

    with pytest.raises(ReleaseError) as excinfo:
        release.decommission(reason="again", actor_id="user-1", at=AT)
    assert excinfo.value.code == "invalid_state"


def test_decommission_without_a_reason_is_refused() -> None:
    release = _release()
    with pytest.raises(ReleaseError) as excinfo:
        release.decommission(reason="", actor_id="user-1", at=AT)
    assert excinfo.value.code == "reason_required"
    assert release.state is ReleaseState.RELEASED


def test_every_transition_is_recorded_in_order() -> None:
    release = _release(previous_release_id="rel-0")
    release.start_canary(percent=5, actor_id="user-1", at=AT)
    release.promote(actor_id="user-1", at=AT)
    release.rollback(reason="regression detected", actor_id="user-2", at=AT)
    release.decommission(reason="retired", actor_id="user-2", at=AT)

    assert [(event.from_state, event.to_state) for event in release.events] == [
        ("released", "canary"),
        ("canary", "promoted"),
        ("promoted", "rolled_back"),
        ("rolled_back", "decommissioned"),
    ]


def test_release_events_are_immutable() -> None:
    release = _release()
    event = release.start_canary(percent=10, actor_id="user-1", at=AT)
    with pytest.raises(FrozenInstanceError):
        event.to_state = "promoted"  # type: ignore[misc]


def test_naive_timestamps_are_rejected() -> None:
    release = _release()
    with pytest.raises(ReleaseError) as excinfo:
        release.start_canary(percent=10, actor_id="user-1", at=datetime(2026, 10, 13))
    assert excinfo.value.code == "naive_datetime"
