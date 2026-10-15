# ADR-0009: Transactional outbox with Redis Streams

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture
**Related**: [contracts/events.md](../contracts/events.md), [research.md](../research.md) R8

## Context

Domain events drive projections, notifications and the dashboard. A missed event
means a stale dashboard or a notification that never arrives; a duplicate event
must not produce a duplicate effect. The platform must also keep working when
the event infrastructure is unavailable, because governance writes must not
depend on it.

## Decision

Use the transactional outbox pattern: state changes write an `outbox_event` row
in the same transaction. A worker relays unpublished rows to Redis Streams.
Consumers are idempotent on `event_id` and deduplicate before applying a
projection. Rows are marked published only after acknowledgement, so a crash
between publish and acknowledge causes redelivery rather than loss.

Redis is chosen because it is already present for caching and locks, so Streams
adds no new operational component at the initial scale. Kafka is the documented
scale-out path.

## Consequences

- At-least-once delivery with exactly-once effects, achieved by deduplication
  rather than by hoping the transport is reliable.
- A governance write succeeds even when the event infrastructure is down; the
  outbox drains later. This is what makes the audit trail independent of the bus.
- Consumers must be written idempotently; this is a real constraint on every
  subscriber and must be part of the development standard.
- Poetry of ordering: events are ordered per aggregate, not globally. Any
  consumer that needs global ordering is asking for the wrong thing.
- The scale-out trigger is explicit — sustained throughput beyond a single Redis
  node, or a need for independent replay guarantees across many consumers.

## Alternatives considered

- **Kafka from the start.** Strong durability and replay, but a broker to
  operate on-premises before the volume justifies it. Kept as the scale-out
  path.
- **RabbitMQ.** Workable, but adds another stateful component for no capability
  the chosen approach lacks at this scale.
- **PostgreSQL LISTEN/NOTIFY.** Simple and transactional, but delivery is lost
  for consumers that are offline, which makes it unsuitable for projections that
  must catch up.
- **Direct publish on write (no outbox).** Rejected: it couples the success of a
  governance write to the availability of the bus, and can lose events on crash.
- **Polling the domain tables for changes.** Rejected: misses intermediate
  states and produces ambiguous ordering.
