"""Tamper-evident audit hash chain.

See ADR-0007 and constitution Principle III. Audit events are written in the
same transaction as the change they describe, and each event stores the hash of
the previous event for the same organisation. Any alteration, reordering or
removal of a row therefore breaks verification.

The chain is deliberately dependency-free: hashing must not depend on a
database, a framework or a message bus, because the audit trail has to remain
verifiable even when those are unavailable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The prev_hash of the first entry in an organisation's chain.
GENESIS_PREV_HASH = "0" * 64

#: Fields covered by the entry hash, in a fixed order. Adding a field here is a
#: breaking change for existing chains and must be accompanied by a migration
#: note (see ADR-0010).
CANONICAL_FIELDS: tuple[str, ...] = (
    "organisation_id",
    "sequence",
    "event_type",
    "actor_type",
    "actor_id",
    "action",
    "target_type",
    "target_id",
    "outcome",
    "reason",
    "occurred_at",
    "recorded_at",
    "correlation_id",
    "detail",
    "prev_hash",
)


def canonical_bytes(entry: Mapping[str, Any]) -> bytes:
    """Return the canonical serialization of an audit entry.

    Serialization is deterministic: sorted keys, no insignificant whitespace,
    and a stable string form for non-string values, so two entries with the same
    semantic content always hash identically.
    """
    payload: dict[str, Any] = {
        field: entry.get(field) for field in CANONICAL_FIELDS if field != "prev_hash"
    }
    payload["prev_hash"] = entry.get("prev_hash", GENESIS_PREV_HASH)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def entry_hash(entry: Mapping[str, Any]) -> str:
    """Return the SHA-256 hex digest of an audit entry's canonical form."""
    return hashlib.sha256(canonical_bytes(entry)).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    """Result of verifying an organisation's audit chain."""

    ok: bool
    checked: int
    broken_at_sequence: int | None = None
    reason: str | None = None


def append_entry(
    previous: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a chained copy of entry, linked after previous.

    Raises:
        ValueError: if a non-success outcome is recorded without a reason, which
            FR-039 forbids.
    """
    outcome = entry.get("outcome")
    reason = entry.get("reason")
    if outcome not in ("success", None) and (reason is None or str(reason).strip() == ""):
        raise ValueError(f"audit outcome {outcome!r} must carry a reason")

    row: dict[str, Any] = dict(entry)
    if previous is None:
        row["sequence"] = 1
        row["prev_hash"] = GENESIS_PREV_HASH
    else:
        row["sequence"] = int(previous["sequence"]) + 1
        row["prev_hash"] = str(previous["entry_hash"])
    row["entry_hash"] = entry_hash(row)
    return row


def verify_chain(entries: Sequence[Mapping[str, Any]]) -> ChainVerification:
    """Verify sequence continuity, hash linkage and integrity of a chain."""
    expected_prev = GENESIS_PREV_HASH
    expected_sequence: int | None = None

    for index, entry in enumerate(entries):
        sequence = entry.get("sequence")
        if sequence is None:
            return ChainVerification(
                ok=False,
                checked=index,
                reason=f"entry at position {index} has no sequence",
            )

        sequence_int = int(sequence)
        if expected_sequence is not None and sequence_int != expected_sequence:
            return ChainVerification(
                ok=False,
                checked=index,
                broken_at_sequence=sequence_int,
                reason=(
                    f"sequence gap at position {index}: "
                    f"expected {expected_sequence}, found {sequence_int}"
                ),
            )

        if str(entry.get("prev_hash", GENESIS_PREV_HASH)) != expected_prev:
            return ChainVerification(
                ok=False,
                checked=index,
                broken_at_sequence=sequence_int,
                reason=f"prev_hash mismatch at sequence {sequence_int}",
            )

        recomputed = entry_hash(entry)
        if recomputed != entry.get("entry_hash"):
            return ChainVerification(
                ok=False,
                checked=index,
                broken_at_sequence=sequence_int,
                reason=f"entry_hash mismatch at sequence {sequence_int}: the row was altered",
            )

        expected_prev = recomputed
        expected_sequence = sequence_int + 1

    return ChainVerification(ok=True, checked=len(entries))
