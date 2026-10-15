# ADR-0011: One authorization decision component for the Permission Center

**Status**: Accepted
**Date**: 2026-10-14
**Deciders**: Platform architecture, Security
**Related**: ADR-0005 (policy engine); Constitution Principles III, V and X;
feature `002-permission-center`

## Context

Feature `001-agent-governance-platform` established a fixed permission matrix for
five built-in roles and enforced it at the API boundary. Feature
`002-permission-center` adds runtime administration of roles, permissions and
scoped assignments, plus resource-level control over Agent ownership.

That creates a real choice. The Permission Center could evaluate permissions
itself — roles and assignments are, after all, ordinary data — or it could route
its decisions through the same policy component already used for tool
invocation. The choice matters because the platform would otherwise end up with
two places that decide whether an action is allowed, and two places that can
disagree.

## Decision

**OPA/Rego remains the single authorization decision component.** The control
plane resolves the caller's effective permissions — role permissions plus
assignments, filtered by scope, expiry and organisation — and assembles them into
a versioned decision input. OPA evaluates
`deploy/policy/authorization.rego` over that input and returns a decision naming
the sources that contributed. Decisions fail closed and are cached briefly,
keyed by organisation and a role-version token that any change invalidates.

Attribute-based rules are added by extending the decision input and the bundle.
No change to roles, assignments or recorded decisions is required, which satisfies
the requirement that ABAC can be adopted later without redesign.

The boundary with feature 001 is fixed at the same time: 001 owns the built-in
roles and its fixed matrix, and the invocation enforcement path; 002 owns the
permission catalogue, role-to-permission binding, scoped assignments, Agent
responsibility, and the resolution of *effective* permissions that the shared
authorization dependency now uses.

## Consequences

- There is one authority for "is this allowed", so a decision cannot differ
  depending on which part of the platform asked.
- Policy remains a reviewable, testable artifact, and its input is versioned, so a
  past decision can be replayed when someone asks why it went that way.
- The request path gains a dependency on OPA. That is acceptable only because
  fail-closed behaviour and decision caching are implemented deliberately, and
  both are tested.
- Effective-permission resolution becomes a real piece of code with a real
  performance budget; it runs on every protected request and is measured at a
  50 ms p95 target.
- Adding attribute-based rules is a policy change rather than a schema change,
  which keeps the extension cheap.

## Alternatives considered

- **Evaluate RBAC in Python and reserve OPA for ABAC.** Superficially simpler, and
  rejected on the same grounds as ADR-0005: two implementations of the same
  decision drift silently, and the drift is invisible exactly when it matters.
- **Encode roles and assignments as policy data, bypassing the database.**
  Unusable: assignments are tenant-scoped, time-bound, audited records that belong
  in the system of record.
- **A bespoke authorisation library in the application layer.** Rejected under
  Principle IX, and it would put policy semantics back inside application code
  where they cannot be reviewed or unit-tested as policy.
- **Leave the split between features 001 and 002 implicit.** Rejected: two
  specifications each assuming they own enforcement is how a bypass appears
  later, and nobody notices until an audit.
