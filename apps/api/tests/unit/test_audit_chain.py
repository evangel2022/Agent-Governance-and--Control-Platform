"""Unit tests for the tamper-evident audit chain (T021)."""

from __future__ import annotations

import pytest

from gov.api.domain.audit.chain import (
    GENESIS_PREV_HASH,
    ChainVerification,
    append_entry,
    canonical_bytes,
    entry_hash,
    verify_chain,
)


def _event(sequence_target: str | None = None, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "organisation_id": "org-1",
        "event_type": "invocation",
        "actor_type": "agent",
        "actor_id": "agent-1",
        "action": "invoke",
        "target_type": "tool",
        "target_id": "tool-1",
        "outcome": "success",
        "reason": None,
        "occurred_at": "2026-10-13T09:00:00Z",
        "recorded_at": "2026-10-13T09:00:01Z",
        "correlation_id": "corr-1",
        "detail": {"risk_level": "low"},
    }
    base.update(overrides)
    return base


def _chain(count: int = 3) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    for index in range(count):
        row = append_entry(previous, _event(detail={"n": index}))
        rows.append(row)
        previous = row
    return rows


def test_first_entry_starts_the_chain() -> None:
    row = append_entry(None, _event())
    assert row["sequence"] == 1
    assert row["prev_hash"] == GENESIS_PREV_HASH
    assert row["entry_hash"] == entry_hash(row)


def test_each_entry_links_to_the_previous_one() -> None:
    rows = _chain(3)
    assert [row["sequence"] for row in rows] == [1, 2, 3]
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert rows[2]["prev_hash"] == rows[1]["entry_hash"]


def test_valid_chain_verifies() -> None:
    verification = verify_chain(_chain(5))
    assert verification == ChainVerification(ok=True, checked=5)


def test_altered_row_is_detected() -> None:
    rows = _chain(3)
    rows[1]["outcome"] = "denied"
    verification = verify_chain(rows)
    assert verification.ok is False
    assert verification.broken_at_sequence == 2
    assert verification.reason is not None and "altered" in verification.reason


def test_deleted_row_is_detected_as_a_sequence_gap() -> None:
    rows = _chain(3)
    del rows[1]
    verification = verify_chain([rows[0], rows[1]])
    assert verification.ok is False
    assert verification.reason is not None and "sequence gap" in verification.reason


def test_reordered_rows_are_detected() -> None:
    rows = _chain(3)
    verification = verify_chain([rows[1], rows[0], rows[2]])
    assert verification.ok is False


def test_non_success_outcome_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="must carry a reason"):
        append_entry(None, _event(outcome="denied", reason=None))


def test_denied_outcome_with_a_reason_is_accepted() -> None:
    row = append_entry(None, _event(outcome="denied", reason="no policy grants this call"))
    assert row["outcome"] == "denied"


def test_canonical_serialization_is_order_independent() -> None:
    left = _event(detail={"a": 1, "b": 2})
    right = _event(detail={"b": 2, "a": 1})
    assert canonical_bytes(left) == canonical_bytes(right)
    assert entry_hash(left) == entry_hash(right)


def test_empty_chain_verifies_trivially() -> None:
    verification = verify_chain([])
    assert verification.ok is True
    assert verification.checked == 0
