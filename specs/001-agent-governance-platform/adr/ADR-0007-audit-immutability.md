# ADR-0007: Append-only hash-chained audit store

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture, Security and Compliance
**Related**: Constitution Principles III and IV; [data-model.md](../data-model.md)

## Context

The audit trail is the platform's product as much as its record: auditors must
be able to reconstruct who did what, under which policy, with whose approval,
and be confident nothing was quietly changed afterwards. The deployment target
is a private environment which may not have WORM-capable storage.

## Decision

Write `audit_event` rows in the same database transaction as the state change
they describe, into an append-only table. Each row carries a per-organisation
monotonic `sequence`, the previous row's hash in `prev_hash`, and its own
`entry_hash` over its canonical fields. The application's database role has no
`UPDATE` or `DELETE` grant on the table. A scheduled job recomputes the chain
and raises a risk event on any mismatch.

Audit writes deliberately do **not** depend on the message bus, so a bus outage
cannot produce an audit gap.

## Consequences

- Tampering is detectable without requiring special storage hardware, which
  matters for the private-deployment requirement.
- Audit and the state change commit atomically, so there is no window in which
  an action exists without its record.
- The chain constrains how rows may be written: a single writer per
  organisation segment is needed to serialize `sequence`, which the gateway and
  control plane must respect.
- Chain verification must run somewhere it cannot be tampered with alongside
  the data; it runs as a separate job with its own credentials and reports into
  the risk-event stream.
- Archiving old events must preserve verifiability, so exports include the
  chain anchors needed to verify the archived segment.

## Alternatives considered

- **Application logs as the audit record.** Rejected: not tamper-evident, not
  transactional with the change, and not a system of record an auditor can
  reconstruct from.
- **WORM object storage as the primary store.** Strongest immutability, but not
  universally available on-premises and awkward for the searchable queries the
  Audit Center requires. Retained as an optional export target.
- **External SIEM as the primary store.** Strong for detection, poor as the
  authoritative record, and it assumes an external system exists.
- **Plain append-only table without chaining.** Simpler, and better than
  nothing, but a privileged operator could alter history undetectably.
