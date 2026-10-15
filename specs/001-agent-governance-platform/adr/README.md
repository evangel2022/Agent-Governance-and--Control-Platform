# Architecture Decision Records

**Feature**: `001-agent-governance-platform`

These records capture decisions that are expensive to reverse. Each states the
context, the decision, the consequences and the alternatives that were
considered, as required by Principle X of the project constitution.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](./ADR-0001-modular-monolith-layered.md) | Modular monolith with enforced layering | Accepted |
| [ADR-0002](./ADR-0002-technology-stack.md) | Technology stack selection | Accepted |
| [ADR-0003](./ADR-0003-mcp-gateway-as-enforcement-point.md) | MCP gateway as the single enforcement point | Accepted (pending Phase 0 spike) |
| [ADR-0004](./ADR-0004-agent-workflow-langgraph.md) | LangGraph for agent workflow orchestration | Accepted (revisit trigger defined) |
| [ADR-0005](./ADR-0005-policy-engine-opa.md) | OPA/Rego as the policy engine | Accepted (pending latency measurement) |
| [ADR-0006](./ADR-0006-runtime-isolation.md) | Runtime isolation for high-risk execution | Accepted |
| [ADR-0007](./ADR-0007-audit-immutability.md) | Append-only hash-chained audit store | Accepted |
| [ADR-0008](./ADR-0008-identity-and-key-management.md) | Keycloak for identity, Vault for keys | Accepted |
| [ADR-0009](./ADR-0009-eventing-outbox-streams.md) | Transactional outbox with Redis Streams | Accepted |
| [ADR-0010](./ADR-0010-schema-migrations.md) | Forward-only migrations with expand/contract | Accepted |
| [ADR-0011](./ADR-0011-authorization-decision-component.md) | One authorization decision component for the Permission Center | Accepted |
