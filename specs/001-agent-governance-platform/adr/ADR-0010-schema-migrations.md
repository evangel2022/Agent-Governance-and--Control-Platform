# ADR-0010: Forward-only migrations with expand/contract

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture
**Related**: Constitution Principle VI; [data-model.md](../data-model.md)

## Context

The constitution requires all database changes to be applied through versioned
migrations, and the platform runs in private environments where the operator
applies upgrades at a time of their choosing. Down-migrations are frequently
unsafe in practice: they destroy data, and they are rarely exercised, so they
are more likely to be wrong precisely when they are needed.

## Decision

Use Alembic with forward-only migrations, following expand/contract for any
change that is not purely additive:

1. **Expand**: add the new structure without removing the old.
2. **Migrate**: backfill and dual-write until the new structure is authoritative.
3. **Contract**: remove the old structure in a later release, after the
   transition is complete.

Destructive changes must document their rollback or roll-forward plan. CI runs
`alembic check` so that a schema drift between the models and the migrations
fails the build. Migrations are reviewed like code.

## Consequences

- Upgrades are safe to apply to a running private deployment, and a failed
  release leaves a consistent schema rather than a half-migrated one.
- Rollback safety comes from the documented plan rather than from a
  down-migration that may never have been tested.
- Contract steps must be scheduled deliberately in a later release; without that
  discipline, obsolete structures accumulate. The migration review checks for
  this.
- Backfills on large tables must be batched and resumable, which is an explicit
  requirement for any migration touching `audit_event` or `invocation`.
- `alembic check` in CI converts schema drift from a production surprise into a
  pull-request failure.

## Alternatives considered

- **Raw SQL scripts applied by hand.** Rejected: no version tracking, no
  reproducibility, and it contradicts Principle VI directly.
- **Framework auto-migration on startup.** Rejected: it makes schema state
  depend on which process started first, and gives operators no control over
  timing in a private deployment.
- **Reversible migrations as the primary safety mechanism.** Rejected as the
  primary mechanism because data-destroying down-migrations are untrustworthy;
  the expand/contract pattern is the real safety net.
- **Schema-as-code with automatic diffing and no review.** Rejected: it
  encourages large implicit changes, which is the opposite of what an audited
  governance platform needs.
