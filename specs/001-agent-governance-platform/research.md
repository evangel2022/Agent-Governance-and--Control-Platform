# Phase 0 Research: Agent Governance and Control Platform

**Feature**: `001-agent-governance-platform`
**Date**: 2026-10-13
**Status**: Complete for all items that block Phase 1 design

This document records the decisions behind the plan. Each item states the
decision, the rationale, and what was rejected. Items explicitly marked
**OPEN** were not resolvable from the specification and are carried as stated
assumptions rather than silently decided.

## R1. Policy decision engine and decision latency

**Decision**: Use OPA (Rego) as the policy engine, queried by the MCP gateway
over its HTTP API, with policies authored as versioned bundles.

**Rationale**: Policy-as-code with a testable unit (`opa test`) matches the
constitution's policy-check requirement and gives an auditable artefact per
decision. Rego input is a plain JSON document, which makes the decision input
(actor, Agent, Tool, risk, environment, window, resolved grants) reproducible
from the audit trail.

**Alternatives considered**: Cedar (better typed model, smaller ecosystem and
weaker sidecar story at the time of writing); a bespoke rule DSL (fastest to
start, worst to audit and test); rules stored in PostgreSQL (couples policy
evaluation to the data layer it is supposed to constrain).

**Measured risk**: an in-process OPA library call is fast; a remote HTTP call can
add tens of milliseconds. The Phase 0 spike must measure p95 against the 150 ms
budget before this is locked in. If the budget is missed, the fallback is the
OPA Go/WASM library on the gateway's hot path rather than changing engines.

## R2. MCP gateway feasibility and fallback

**Decision**: Introduce an MCP gateway as the single enforcement point, built on
the MCP SDK if the reference implementation cannot meet the enforcement
requirements.

**Rationale**: The specification requires authentication, authorization, policy
and audit on every tool call. Concentrating that in one component makes
"no ungoverned tool call" a structural property rather than a discipline.

**Alternatives considered**: direct tool adapters per Agent (no single
enforcement point, each integration re-implements governance); a service mesh
policy layer (handles transport authN but not domain-level risk and approval
semantics).

**Measured risk**: the MCP ecosystem is young. Phase 0 must prove (a) a full
round trip with an audit write, and (b) fail-closed behaviour when OPA is
unreachable. If the reference gateway cannot do both, the same contract is
implemented as a thin bespoke gateway with no change to the control plane.

## R3. Agent workflow orchestration

**Decision**: Use LangGraph for multi-step, approval-gated agent workflows, and
keep the governance decision path outside the graph so a workflow cannot route
around enforcement.

**Rationale**: LangGraph's explicit graph and checkpointed state suit workflows
that pause for human approval and resume. Crucially, the governance decision is
not a graph node that an author can reorder — it is a gateway property.

**Alternatives considered**: Temporal (stronger durability and resumability,
heavier operational footprint for the initial phase); Airflow (batch-oriented,
poor fit for interactive approval); a bespoke state machine (more control, more
bespoke code, contradicting the reuse principle).

**Revisit trigger**: workflows that must resume across processes at scale, or
long-running executions beyond the checkpoint model's comfortable envelope.

## R4. Runtime isolation for high-risk and untrusted tasks

**Decision**: Two sandbox classes. Low/medium risk tools run in a shared,
restricted container pool. High/critical risk tools run in a dedicated sandbox
per execution, with no ambient credentials, a read-only filesystem, dropped
capabilities, a seccomp profile, no default egress, and a dedicated node pool on
Kubernetes.

**Rationale**: Risk-proportionate isolation avoids paying full sandbox cost for
inventory reads while giving financially consequential operations a materially
stronger boundary.

**Alternatives considered**: one isolation level for everything (either
expensive or under-protective); microVMs (Firecracker) for all high-risk work
(strongest isolation, significant operational cost on-premises; retained as an
upgrade path via a Kubernetes runtime class); separate clusters per risk tier
(cleanest separation, heaviest for a first release).

## R5. Multi-tenant isolation mechanism

**Decision**: Enforce isolation in the data layer with `organisation_id` on every
aggregate plus PostgreSQL row-level security driven from the session's
organisation claim, in addition to application-level scope checks.

**Rationale**: Application-level filtering alone fails open on the first missing
`WHERE` clause. Row-level security makes cross-tenant reads impossible even when
the application is wrong, which is the standard for enterprise deployments.

**Alternatives considered**: schema-per-tenant (strong, awkward migrations
across many tenants); database-per-tenant (strongest, operationally heavy and a
poor fit for a single private deployment); application filtering only (rejected
above).

**OPEN (FR-036)** — whether a deployment serves one organisation or many is
unresolved. The decision above implements the stricter case, which is correct
under either answer; a single-organisation deployment is simply a one-row case.

## R6. Audit immutability

**Decision**: Write audit events in the same database transaction as the state
change they describe, into an append-only table with a per-organisation hash
chain (`prev_hash`, `entry_hash`). A scheduled verifier recomputes the chain.

**Rationale**: Audit records must survive a message-bus outage, which rules out
writing audit only from a stream consumer. Hash chaining makes tampering
detectable without requiring WORM hardware, which matters for private
deployments that may not have object-lock capable storage.

**Alternatives considered**: application-log scraping (rejected: not
tamper-evident, not queryable as a system of record); WORM object storage
(strongest, not universally available on-premises, retained as an optional
export target); an external SIEM as the primary store (good for detection, poor
as the record an auditor reconstructs from).

## R7. Identity and key management

**Decision**: Keycloak for human identity (OIDC), HashiCorp Vault (KV v2 and
Transit) for secrets and key material, agent identities bound to an
`agent_version` with keys held in Vault.

**Rationale**: Both components are self-hostable, air-gap friendly and widely
operated, which the private-deployment requirement demands. Cloud identity and
key services were excluded because they assume egress.

**Alternatives considered**: platform-managed passwords (rejected: weaker and
out of step with enterprise deployments); cloud KMS services (rejected for
air-gapped on-premises); Kubernetes Secrets as the store (rejected: not a key
management system, no rotation or audit story).

## R8. Eventing and asynchronous processing

**Decision**: Transactional outbox in PostgreSQL, relayed to Redis Streams by a
worker, with idempotent consumers keyed on `event_id`.

**Rationale**: The outbox gives exactly-once *effects* at the cost of
at-least-once *delivery*, and it does not require a broker to be up for a
governance write to succeed. Redis is already present for caching and locks, so
Streams adds no new operational component at the initial scale.

**Alternatives considered**: Kafka (the documented scale-out path once event
volume or consumer count justifies a broker); RabbitMQ (fine, another
component); Postgres LISTEN/NOTIFY (simple but lossy for consumers that are
offline).

**Scale-out trigger**: sustained event throughput beyond what a single Redis
node comfortably handles, or a requirement for independent consumer replay
guarantees across many consumers.

## R9. Contract-first API and schema stability

**Decision**: Author OpenAPI 3.1 as the contract for the control plane, generate
the TypeScript client from it, and run Schemathesis against the running
application in CI.

**Rationale**: The constitution requires every API to have a machine-checkable
contract and automated tests. Generating rather than hand-maintaining the client
removes a class of drift, and Schemathesis converts the document into live
conformance tests.

**Alternatives considered**: code-first without a published document (drift
between the implementation and consumers); gRPC (good for internal services,
poor fit for a browser-facing admin console and for third-party integrations).

## R10. Testing approach for security-critical behaviour

**Decision**: Treat authorization, deny-by-default and fail-closed behaviour as
first-class test targets with a per-role permission matrix test, forced-dependency
failure tests, and explicit negative tests for self-approval and replay.

**Rationale**: These are the behaviours whose absence would invalidate the
product, and they are exactly the behaviours that ordinary happy-path tests do
not exercise.

**Alternatives considered**: relying on integration tests alone (they rarely
enumerate the permission matrix); manual security review only (not repeatable
per change).

## Open items carried into planning

These are unresolved questions from the specification. They are recorded here so
that no reader mistakes an assumption for a settled requirement.

| Ref | Question | Assumption used in the plan | Impact if the answer differs |
|-----|----------|------------------------------|------------------------------|
| FR-037 | Which capabilities form the first runnable release? | P1 (User Stories 1–3) | Scope of Phases 2–5 changes; architecture does not |
| FR-036 | One organisation per deployment, or many? | Many, with enforced separation | None architecturally; a single-organisation deployment is a one-row case |
| FR-022 | Single approver or dual control; may a requester self-approve? | Single approver; self-approval refused | Approval state machine gains a second decision step, already modelled |
| Open business rule 1 | What makes a Tool high risk? | Declared per Tool, optionally escalated per invocation | Risk classification input changes; enforcement does not |
| Open business rule 2 | Approval routing, delegation, escalation | Single designated approver per organisation scope | Routing module grows; state machine unchanged |
| Open business rule 8 | Canary criteria and automatic vs manual promotion | Manual promotion, configurable portion | Release Center gains automation |
| Open business rule 9 | Evaluation criteria and thresholds | Criteria provided per evaluation task | Evaluation Center stays generic |
| Open business rule 11 | Data residency constraints | Single-region private deployment | If per-region is required, deployment topology changes before Phase 7 |

## Summary of resolved unknowns

All Technical Context unknowns are resolved: language and runtime versions,
dependencies, storage, testing tools, target platform, performance budgets and
scale assumptions are fixed in [plan.md](./plan.md). The only remaining
unresolved items are business-rule questions, listed above, and none of them
blocks Phase 1 design.
