# ADR-0001: Modular monolith with enforced layering for the control plane

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture
**Related**: Constitution Principle I; [plan.md](../plan.md)

## Context

Governance state (registries, policies, approvals, audit) is deeply
interdependent: a single policy change touches policy versions, derived grants,
in-flight approvals and audit records. Splitting that state across services would
introduce distributed transactions on the hot path, in a product whose core value
is a trustworthy, reconstructable record of what happened.

At the same time, the invocation path has different scaling, failure and
isolation characteristics from the administrative path, and must be able to fail
closed without depending on the control plane being healthy.

## Decision

Build the control plane as a **modular monolith** with four enforced layers
(`interface` → `application` → `domain`, with `infrastructure` providing
outward adapters). Enforce the layer boundaries with an automated import check in
CI rather than by convention. Deploy the invocation path (MCP gateway) and the
execution runtime (runner) and the async processor (worker) as separate
processes.

## Consequences

- One transaction boundary covers related governance writes, so an audit record
  can be written atomically with the change it describes.
- Module boundaries remain enforceable and refactorable; extracting a module
  into a service later is a deployment change rather than a rewrite, because the
  interfaces are already explicit.
- The team must resist letting the `application` layer reach around `domain`
  logic; the import check makes drift a build failure rather than a review
  opinion.
- A control-plane outage degrades administration but cannot open a path around
  enforcement, because enforcement lives in the gateway.

## Alternatives considered

- **Microservices from the start.** Rejected: distributed transactions on
  governance writes, plus operational overhead disproportionate to the initial
  scale, with no benefit that the modular monolith does not already provide.
- **Single service including the gateway and runner.** Rejected: couples the
  security-critical enforcement path to the administrative path's availability
  and scaling, and makes isolation harder to reason about.
- **Layered monolith without enforcement tooling.** Rejected: layering that is
  only a convention erodes; the import check costs little and makes the
  boundary real.
