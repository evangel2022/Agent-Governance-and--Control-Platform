# ADR-0006: Runtime isolation for high-risk and untrusted execution

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture, Security
**Related**: Constitution Principles IV and V; [contracts/mcp-gateway.md](../contracts/mcp-gateway.md)

## Context

Tools range from read-only inventory lookups to operations that move money or
alter purchase orders. Tool code may be third-party or model-influenced, so it
must be treated as untrusted. Isolating everything as strongly as the riskiest
tool would be prohibitively expensive; isolating everything the same way would
be under-protective for the operations that matter most.

## Decision

Two sandbox classes, selected by the Tool's risk level:

- **Shared pool** for low/medium risk: restricted container, read-only
  filesystem, dropped capabilities, seccomp profile, explicit egress
  allow-list, no ambient credentials.
- **Dedicated sandbox per execution** for high/critical risk: no ambient
  credentials, no default egress, short-lived narrowly scoped credentials
  minted per execution and revoked at completion. On Kubernetes these run on a
  separate node pool with a distinct runtime class.

The runner never receives database credentials and cannot write governance state
directly; anything it must report travels back through the gateway.

## Consequences

- Isolation cost is proportional to risk, so the platform remains affordable
  while consequential operations get a materially stronger boundary.
- Two execution paths must be maintained and tested; the security suite must
  cover both, and the gateway's dispatch decision must be auditable.
- Credential minting per execution adds a dependency on Vault on the dispatch
  path; a Vault outage results in denial rather than execution with stale
  credentials.
- A future move to microVMs is a runtime-class change rather than a
  re-architecture, because the ceiling is already drawn at the sandbox.

## Alternatives considered

- **One isolation level for all tools.** Rejected in both directions: either
  expensive or under-protective.
- **MicroVMs (Firecracker) for everything.** Strongest isolation, but
  significant operational cost on-premises and a steep barrier for customers
  running a single-node install. Retained as an upgrade via the Kubernetes
  runtime class.
- **Separate clusters per risk tier.** Cleanest separation, heaviest operation
  for a first release; possible later without changing the application
  contract.
- **No isolation (run tool code in the gateway process).** Rejected outright:
  a single compromised tool would gain the enforcement path's own privileges.
