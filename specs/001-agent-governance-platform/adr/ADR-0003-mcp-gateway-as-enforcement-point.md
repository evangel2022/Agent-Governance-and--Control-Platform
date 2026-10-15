# ADR-0003: MCP gateway as the single enforcement point for tool invocation

**Status**: Accepted (contingent on the Phase 0 spike)
**Date**: 2026-10-13
**Deciders**: Platform architecture, Security
**Related**: Constitution Principle III; [contracts/mcp-gateway.md](../contracts/mcp-gateway.md)

## Context

The constitution requires that **every** Agent tool call pass through
authentication, authorization, policy checks and auditing before execution. If
governance is implemented per integration, correctness depends on every
integration author remembering to implement it, and a single omission becomes an
ungoverned action.

## Decision

Introduce an MCP gateway as the only path from an Agent to a Tool. The gateway
applies authentication, authorization, policy, risk classification, approval and
audit in a fixed order, and fails closed when any enforcement dependency is
unavailable. Tool adapters are reachable only through the gateway; the runner
accepts dispatch only from the gateway's workload identity.

The gateway is built on the MCP SDK. If the Phase 0 spike shows that no
available implementation can meet the audit-completeness and fail-closed
requirements, a thin bespoke gateway implementing the same contract is
substituted, without changing the control plane.

## Consequences

- "No ungoverned tool call" becomes a structural property rather than a
  discipline that depends on integration authors.
- The gateway is on the critical path, so its availability and latency directly
  bound the platform; it must be horizontally scalable and independently
  deployable.
- The MCP ecosystem is young. This decision carries integration risk that the
  Phase 0 spike is explicitly designed to retire, and a documented fallback
  exists if it cannot be retired.
- Tool adapters gain a stable contract, which decouples tool onboarding from
  governance changes.

## Alternatives considered

- **Direct tool adapters per Agent.** Rejected: no single enforcement point;
  governance correctness depends on every integration.
- **Service-mesh policy only.** Rejected: a mesh handles transport-level
  authentication and coarse authorization but has no concept of tool risk
  level, approval workflow or governance audit semantics.
- **Governance library embedded in each Agent runtime.** Rejected: distributes
  the security-critical decision into code the platform cannot verify or
  upgrade centrally, and cannot fail closed on behalf of the platform.
- **Wait for the MCP ecosystem to mature.** Rejected: delays the core value and
  does not remove the requirement; the fallback path bounds the risk.
