# ADR-0005: OPA/Rego as the policy-as-code engine

**Status**: Accepted (contingent on the Phase 0 latency measurement)
**Date**: 2026-10-13
**Deciders**: Platform architecture, Security and Compliance
**Related**: Constitution Principle III; [research.md](../research.md) R1

## Context

Policy must be authored, reviewed, versioned, tested and — critically —
cited in audit records so that a reviewer can see which policy produced a
decision. Policies also change far more often than the platform's code.

## Decision

Use Open Policy Agent with Rego. Policies are versioned artefacts published as
bundles with a stable digest; every judgement records the policy version and
digest applied. The gateway queries OPA and records the answer; it never
implements policy logic itself.

The Phase 0 spike must measure the p95 decision latency against the 150 ms
budget. If a remote call cannot meet it, the fallback is to run the same Rego
via an embedded evaluation library rather than to change engines.

## Consequences

- Policy becomes a reviewable, testable artefact (`opa test`) rather than
  configuration scattered across the codebase.
- The audit trail can name precisely which policy version decided an outcome,
  which is what makes decisions defensible to an auditor.
- Rego's expressiveness is a double-edged sword: poorly written policies are
  hard to read, so a policy style guide and mandatory tests accompany adoption.
- OPA becomes a dependency on the enforcement hot path, which is acceptable
  only because fail-closed behaviour is explicitly implemented and tested.

## Alternatives considered

- **Cedar.** A cleaner, more typed authorization language, but a smaller
  ecosystem, less operational familiarity and a weaker sidecar deployment story
  at the time of this decision.
- **Custom rule DSL.** Fastest to start and cheapest to explain, but the most
  expensive to audit and test, and it puts policy semantics inside bespoke code.
- **Rules stored as rows in PostgreSQL.** Rejected: it couples policy
  evaluation to the data layer it is meant to constrain, and makes independent
  policy testing and bundle versioning awkward.
- **Hard-coded authorization logic.** Rejected: policy change would become a
  code release, which directly contradicts the requirement that authorized
  users configure policies.
