# Agent Governance and Control Platform

Enterprise-grade Agent governance and control for private deployment, serving
ERP, finance and supply chain scenarios.

The platform gives an organisation an authoritative inventory of Agents, Tools
and Models; evaluates every Agent tool invocation against policy; requires
accountable human approval for high-risk operations; and records every governed
action in a tamper-evident audit trail.

## Layout

| Path | Purpose |
|------|---------|
| `apps/api` | Control plane (Python, FastAPI) |
| `apps/web` | Operator and approver console (React, TypeScript) |
| `services/gateway` | MCP gateway: the single invocation enforcement point |
| `services/runner` | Isolated execution runtime for tool dispatch |
| `services/worker` | Async jobs: expiry, outbox relay, evaluation, retention |
| `deploy/compose` | Docker Compose development stack |
| `deploy/policy` | OPA/Rego policy bundle and style guide |
| `deploy/helm` | Kubernetes charts for on-premises production |
| `specs/001-agent-governance-platform` | Specification, plan, tasks and ADRs |
| `docs/runbooks` | Operator runbooks |

## Documentation

Start with the feature artifacts in `specs/001-agent-governance-platform`:
`spec.md` (what and why), `plan.md` (how), `data-model.md`, `contracts/`,
`adr/` (decisions and trade-offs) and `tasks.md` (execution order).

Project governance lives in `.specify/memory/constitution.md`; it supersedes
other practices where they conflict.

## Getting started

See `specs/001-agent-governance-platform/quickstart.md` for the development
stack, migrations, seeding and the acceptance walkthrough.
