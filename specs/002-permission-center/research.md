# Phase 0 Research: Permission Center

**Feature**: `002-permission-center`
**Date**: 2026-10-14
**Status**: Complete for every item that blocks Phase 1 design

## R1. Where the decision is made

**Decision**: one decision component (OPA/Rego), fed by an effective-permission
input assembled in the control plane. Recorded in ADR-0011.

**Rationale**: ADR-0005 already makes OPA the single authority for allow/deny.
Adding a second evaluator for RBAC would create two answers to the same question,
and the divergence would surface only when someone asked why an action was
permitted.

**Alternatives considered**: RBAC in Python with OPA reserved for ABAC; policy
data held inside OPA; a bespoke authorisation library. All rejected in ADR-0011.

## R2. Built-in roles versus organisation roles

**Decision**: the five built-in roles are immutable baselines, seeded by
migration. Organisation-specific roles are created alongside them (FR-031,
clarified 2026-10-14).

**Rationale**: the platform's own governance depends on those roles existing —
policy authoring and high-risk approval among them. Making them editable lets an
organisation remove its own ability to administer the platform, which FR-027
already guards against.

**Alternatives considered**: fully editable built-ins (simpler mental model, but
removes the safety baseline); replacing the built-ins with the four user types
named in the request (would have removed policy authoring and approval roles).

## R3. Effective permission resolution

**Decision**: resolve per request from role permissions plus assignments, filtered
by organisation, scope and expiry, then cache the result against a role-version
token.

**Rationale**: the resolution runs on every protected request, so it must be
bounded. A role-version token makes invalidation exact rather than time-based,
which is what lets a revocation take effect at the next verification (FR-020)
without a cache-busting query on every call.

**Alternatives considered**: no cache (correct, but a query per request against
several tables); time-based TTL only (would leave a window in which a revoked
permission still works, which FR-020 forbids).

## R4. Scope of an assignment

**Decision**: an assignment is scoped to an organisation, to a named Agent, or to
both, and carries an optional end date. It never grants outside its scope.

**Rationale**: it reuses the `role_assignment` table and its `scope_type` /
`scope_id` shape from `0001_identity`, including the `NULLS NOT DISTINCT` unique
constraint that stops an organisation-scoped grant being duplicated.

**Alternatives considered**: a separate table for Agent-scoped grants (a second
place to look for the same answer); expressing scope inside policy data (removes
it from the system of record, where it must be auditable).

## R5. Agent responsibility

**Decision**: a dedicated `agent_responsibility` record per Agent, with transfer
history retained in the audit trail.

**Rationale**: the Agent Registry schema already has `owner_user_id` as the
accountable person. Responsibility is that same fact made explicit and
transferable, with the transfer audited, rather than a second competing notion of
ownership.

**Alternatives considered**: reuse `owner_user_id` with no separate record (no
place to state a transfer reason); infer responsibility from assignments (does
not express who is accountable, only what someone may do).

**Open**: whether accountability may be shared is unresolved (spec open rule 1).
The design assumes exactly one accountable person and would need a join record
rather than a column if that changes.

## R6. Recording permission changes

**Decision**: write permission changes to the existing `audit_event` trail, in the
same transaction as the change, rather than adding a domain-specific change table.

**Rationale**: the trail is already append-only and tamper-evident with a hash
chain (ADR-0007), and its `target_type`/`target_id` index already answers "every
change to this role or assignment". A second table would duplicate the guarantee
and weaken it, because two trails can disagree.

**Alternatives considered**: a `permission_change` table (duplicates the audit
guarantee); database triggers (contrary to ADR-0007, and invisible to reviewers).

## R7. Read-only assurance for auditors

**Decision**: the auditor role holds read permissions only, and the absence of
write authority is asserted by a test rather than by convention.

**Rationale**: FR-024 requires refusal, and SC-008 measures it. A test that proves
every write is refused is the only way to keep that true as routes are added.

**Alternatives considered**: relying on the permission matrix (a new route can be
added without a corresponding permission and default-open by omission; the
deny-by-default rule prevents that, and the test proves it).

## R8. Migration placement

**Decision**: one new revision, `0005_permission_center`, chaining after
`0004_tool_registry`.

**Rationale**: the identity, assignment and audit tables already exist; this
revision adds the permission catalogue, the role-to-permission binding, and Agent
responsibility. It follows the registry revisions because those tables reference
Agents.

**Alternatives considered**: extending `0001_identity` (rewriting an applied
migration, forbidden); a separate database for permissions (splits the tenancy
model).

## Open items carried into planning

| Ref | Question | Assumption used | Impact if different |
|-----|----------|-----------------|---------------------|
| Spec open rule 1 | One accountable person per Agent, or several? | Exactly one | `agent_responsibility` becomes a join table; the rule changes, the architecture does not |
| Spec open rule 2 | May a holder delegate an assignment? | No: only an administrator grants or revokes | Delegation adds a grant path and its own audit rule |
| Spec open rule 3 | Retention period for permission-change records | Same as the audit trail (at least one year) | Retention configuration only |
