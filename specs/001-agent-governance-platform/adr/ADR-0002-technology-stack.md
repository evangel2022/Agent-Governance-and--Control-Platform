# ADR-0002: Technology stack selection

**Status**: Accepted
**Date**: 2026-10-13
**Deciders**: Platform architecture
**Related**: Constitution Principle IX; [plan.md](../plan.md)

## Context

The specification deliberately deferred the technology stack. It must now be
chosen, under two hard constraints from the requirements: the platform must
support **private, including air-gapped, deployment**, and the stack must reuse
mature components rather than build novel infrastructure.

## Decision

- **Backend**: Python 3.12 with FastAPI, Pydantic v2, SQLAlchemy 2.0 (async),
  Alembic, asyncpg.
- **Frontend**: React 18 with TypeScript 5.6, Vite, TanStack Query, Ant Design.
- **Database**: PostgreSQL 16.
- **Cache and short-term state**: Redis 7.
- **Testing and quality**: pytest, httpx, testcontainers, Schemathesis, Vitest,
  Playwright, ruff, mypy, eslint, tsc, k6.

## Consequences

- Every component is self-hostable and air-gap friendly, which the private
  deployment requirement makes non-negotiable.
- Typed request/response models and generated OpenAPI satisfy the constitution's
  contract requirement without duplicated schema maintenance.
- PostgreSQL provides row-level security and JSONB, both used directly by the
  isolation and audit designs rather than bolted on.
- The team carries two language toolchains; this is accepted as the cost of a
  typed SPA plus a Python control plane.
- Python's concurrency model means CPU-heavy work must not block the event loop;
  heavy evaluation runs go to the worker and runner rather than the API.

## Alternatives considered

- **Django REST Framework.** Rejected: heavier, synchronous ORM by default,
  weaker fit for the async governance hot path, and its admin is not a
  substitute for the governance console.
- **Litestar.** Rejected: comparable capability but a smaller ecosystem and less
  team familiarity for no compensating benefit.
- **MySQL or SQL Server.** Rejected: PostgreSQL's row-level security is the
  cleanest available mechanism for the tenant-isolation design, and JSONB plus
  mature on-premises tooling are advantages.
- **Vue or Angular.** Rejected: not needed for the governance console, and the
  team's existing React/TypeScript familiarity reduces delivery risk.
- **Node.js backend.** Rejected: weaker fit for the data-processing and
  evaluation workloads than Python, with no offsetting advantage.
