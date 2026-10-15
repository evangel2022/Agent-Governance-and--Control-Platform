---

description: "Task list for the Agent governance and control platform"
---

# Tasks: Agent Governance and Control Platform

**Input**: Design documents from `/specs/001-agent-governance-platform/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md), [adr/](./adr/README.md)

**Tests**: Included. The project constitution (Principles II and VIII) makes
automated testing mandatory for every API, so test tasks are first-class
deliverables rather than optional extras.

**Organization**: Tasks are grouped by user story so each story can be
implemented, tested and demonstrated independently.

## Category Legend

Every task carries one of the six requested categories immediately after its
identifier:

| Category | Meaning |
|----------|---------|
| Infrastructure | Runtime, deployment, tooling and platform plumbing |
| Data Model | Schema, migrations, ORM mappings, domain entities |
| Backend API | Use cases, repositories, routers, contracts |
| Permission & Audit | Authentication, authorization, policy, approval enforcement, audit integrity, key management |
| Frontend UI | React and TypeScript surfaces and their generated clients |
| Automated Testing | Test suites, harnesses and verification tooling |

## Format: `[ID] [P?] [Story?] Category - Description with file path`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1-US8); absent in Phase 0, Setup, Foundational and Polish phases
- Every task states the exact file path, its deliverable, and how to verify it

## Path Conventions

Paths follow the structure fixed in plan.md: `apps/api/`, `apps/web/`,
`services/gateway/`, `services/runner/`, `services/worker/`, `libs/contracts/`,
`deploy/`, and the feature directory `specs/001-agent-governance-platform/`.

---

## Phase 0: Feasibility Spike (Execute Before Everything Else)

**Purpose**: retire the three risks that could invalidate the architecture, as
required by plan.md "Phases" and "Feasibility, Module Boundary and Security Risk
Verification". These tasks produce evidence, not product code.

**GATE**: Phase 1 must not begin until all four spikes report a result. If the
OPA latency spike misses the budget, apply the embedded-evaluation fallback in
ADR-0005; if the gateway spike cannot meet fail-closed and audit completeness,
apply the fallback in ADR-0003.

- [ ] T001 [P] Permission & Audit - Measure OPA p95 decision latency for the realistic decision-input shape and record the result against the 150 ms budget in `specs/001-agent-governance-platform/research.md`. Deliverable: a reproducible measurement and a go/no-go against ADR-0005. Verify: a committed script prints p50 and p95, and the recorded figure is compared with the Phase 0 exit criteria in plan.md.
- [ ] T002 [P] Infrastructure - Prove an MCP gateway round trip with an audit write against a stub tool adapter in `specs/001-agent-governance-platform/spike/mcp-gateway/`. Deliverable: an end-to-end trace of one governed invocation. Verify: the trace shows a recorded audit row, and stopping OPA produces a denial rather than a default allow (ADR-0003).
- [ ] T003 [P] Infrastructure - Produce and validate the sandbox escape checklist for the shared and dedicated isolation settings in `specs/001-agent-governance-platform/spike/sandbox/`. Deliverable: a checklist with recorded evidence per item. Verify: every checklist item has observed evidence, and any unmitigated item is escalated before Phase 1 (ADR-0006).
- [ ] T004 [P] Data Model - Prove row-level-security isolation with two seeded organisations in `specs/001-agent-governance-platform/spike/rls/`. Deliverable: a documented proof for FR-036. Verify: a query issued without tenant context returns zero rows, and an unmapped policy is shown to fail closed.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: create a repository skeleton whose quality gates and local stack
exist before any feature work begins, so every later task lands on a green
pipeline.

- [X] T005 Infrastructure - Create the monorepo skeleton (`apps/api`, `apps/web`, `services/gateway`, `services/runner`, `services/worker`, `libs/contracts`, `deploy/compose`, `deploy/helm`, `deploy/policy`, `docs/runbooks`) plus root `README.md` and `.gitignore`. Deliverable: the tree specified in plan.md "Project Structure". Verify: the directory listing matches plan.md and no source file contains placeholder code.
- [ ] T006 Infrastructure - Author `apps/api/pyproject.toml` with Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, asyncpg, httpx, pytest, pytest-asyncio, ruff, mypy, schemathesis. Deliverable: installable control-plane package. Verify: `pip install -e apps/api` and `python -c "import fastapi, sqlalchemy, alembic"` succeed.
- [ ] T007 [P] Infrastructure - Author `apps/web/package.json` and `apps/web/vite.config.ts` with React 18, TypeScript 5.6, Vite, TanStack Query, Ant Design, Vitest and Playwright. Deliverable: buildable SPA scaffold. Verify: `npm ci` then `npm run build` exit zero.
- [ ] T008 [P] Infrastructure - Author `services/gateway/pyproject.toml`, `services/runner/pyproject.toml` and `services/worker/pyproject.toml` with their runtime and test dependencies. Deliverable: three installable service packages. Verify: each installs and imports its top-level module.
- [ ] T009 Infrastructure - Author `deploy/compose/compose.yml` and `deploy/compose/.env.example` with postgres, redis, opa, vault (dev), keycloak, api, gateway, runner, worker and web services, including health checks and non-secret configuration only. Deliverable: a reproducible local stack. Verify: `docker compose -f deploy/compose/compose.yml config` validates and `up -d` reports every service healthy.
- [ ] T010 [P] Infrastructure - Author the OPA policy bundle scaffold in `deploy/policy/` with a minimal Rego module and an `opa test` case. Deliverable: a testable bundle. Verify: `opa test deploy/policy` passes with at least one test.
- [ ] T011 [P] Infrastructure - Author `deploy/compose/keycloak/realm.json` importing the five built-in roles and one demo account per role. Deliverable: importable realm. Verify: after `up -d`, the realm discovery document returns 200 and all five accounts authenticate.
- [ ] T012 [P] Infrastructure - Author `deploy/compose/vault/bootstrap.sh` enabling the KV v2 mount and a Transit key, idempotently. Deliverable: repeatable Vault bootstrap. Verify: running it twice exits zero and listing secrets succeeds.
- [ ] T013 Infrastructure - Author the root `Makefile` with `lint`, `test`, `test-contract`, `test-security`, `test-e2e`, `db-upgrade`, `seed` and `audit-verify`. Deliverable: one-command developer entry points. Verify: `make -n lint` prints the expected underlying commands.
- [ ] T014 [P] Infrastructure - Implement OpenTelemetry tracing and metrics wiring in `apps/api/src/gov/api/infrastructure/telemetry.py`. Deliverable: instrumented app startup. Verify: a unit test asserts a tracer provider is configured and a span is emitted for a sample request.
- [ ] T015 Infrastructure - Author `.github/workflows/ci.yml` implementing all nine blocking gates from plan.md (ruff and mypy, eslint and tsc, import-linter, pytest, schemathesis, opa test, pip-audit and npm audit, trivy, gitleaks, coverage and alembic check). Deliverable: a CI pipeline. Verify: the workflow parses and a draft pull request executes every gate, including a deliberate failing case that blocks the merge.
- [ ] T016 [P] Infrastructure - Author lint and boundary configuration in `ruff.toml`, `mypy.ini`, `apps/web/.eslintrc.cjs` and `.importlinter`, encoding the interface to application to domain layers. Deliverable: enforceable layering. Verify: `lint-imports` reports the layered contract satisfied and fails when a deliberate violation is introduced.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared capabilities that every user story depends on. No user story
work may begin until this phase is complete.

**CRITICAL**: Phase 2 blocks all of Phase 3 onwards.

- [ ] T017 Data Model - Configure Alembic in `apps/api/alembic.ini` and `apps/api/migrations/env.py`, sourcing the database URL from Vault rather than a file, and add the migration review rule that every non-additive migration carries a documented rollback or roll-forward plan (constitution Principle VI). Deliverable: working migration runner plus the review rule. Verify: `alembic upgrade head` on an empty database creates `alembic_version`, and a test migration with no rollback note is rejected by the review check.
- [ ] T018 Data Model - Baseline migration `apps/api/migrations/versions/0001_identity.py` creating `organisation`, `user`, `role` and `role_assignment` with `organisation_id NOT NULL` where applicable and RLS policies bound to `app.organisation_id`. Deliverable: identity schema. Verify: `alembic upgrade head` succeeds and `pg_policies` lists a policy for each tenant table.
- [ ] T019 Permission & Audit - Migration and configuration for per-service database roles granting minimum privileges, with no `UPDATE` or `DELETE` on audit tables for the application role. Deliverable: least-privilege database access. Verify: an integration test asserts the application role receives a permission error when updating an audit table.
- [ ] T020 Data Model - Implement the `outbox_event` table, ORM model and writer in `apps/api/src/gov/api/infrastructure/outbox/`. Deliverable: transactional outbox. Verify: a unit test asserts the outbox row is rolled back together with a failing business transaction.
- [X] T021 Permission & Audit - Implement the audit hash-chain primitive (canonical field serialization, `prev_hash` linkage, `entry_hash` computation) in `apps/api/src/gov/api/domain/audit/chain.py`. Deliverable: tamper-evident chaining. Verify: unit tests cover a first-row null `prev_hash`, correct linkage, and detection of a mutated row.
- [ ] T022 Permission & Audit - Implement tenant context middleware binding `app.organisation_id` for RLS in `apps/api/src/gov/api/interface/middleware/tenant.py`. Deliverable: enforced tenant scoping. Verify: an integration test asserts a query issued without tenant context returns zero rows.
- [X] T023 Permission & Audit - Implement the OIDC/JWT dependency in `apps/api/src/gov/api/interface/security/oidc.py` with JWKS caching plus issuer and audience validation. Deliverable: authenticated request context. Verify: tests cover a valid token, an expired token, a wrong-audience token and a malformed token.
- [X] T024 Permission & Audit - Implement the role permission matrix in `apps/api/src/gov/api/domain/identity/permissions.py` covering all five roles, with `approval.decide` as a permission independent of administrator status and deny-by-default for unmapped actions. Deliverable: the authorization model. Verify: a table-driven unit test enumerates every role and action, including the unmapped case.
- [X] T025 Permission & Audit - Implement the authorization dependency (permission plus scope) in `apps/api/src/gov/api/interface/security/authorize.py`. The dependency evaluates the permissions already resolved onto the principal, so it refuses an unauthenticated request and any caller lacking a required permission; resolving which assignments are still valid (including lapsed time-bound grants) belongs to the application layer that builds the principal, and is enforced by T043. Deliverable: reusable endpoint guard. Verify: unit tests assert an unauthenticated request is refused, that a caller lacking any required permission receives a 403 naming every missing permission, and that combined roles satisfy combined requirements; per-endpoint coverage arrives with the endpoints and is owned by T043.
- [ ] T026 Permission & Audit - Implement the Vault client and Transit encryption helper for sensitive columns in `apps/api/src/gov/api/infrastructure/vault/`. Deliverable: application-level encryption. Verify: an integration test round-trips a value against Vault dev, and a second test asserts requests fail closed when Vault is unreachable.
- [X] T027 Backend API - Implement the application factory, middleware stack and RFC 9457 problem-detail error handling in `apps/api/src/gov/api/main.py` and `apps/api/src/gov/api/interface/errors.py`. Deliverable: consistent error contract. Verify: a contract test asserts validation failures return `application/problem+json` with `type`, `title`, `status` and per-field errors.
- [X] T028 Backend API - Implement pagination, request-id and structured logging helpers in `apps/api/src/gov/api/interface/pagination.py`, normalising every emitted timestamp to UTC. Deliverable: shared interface utilities. Verify: unit tests cover page-token round-trips, rejection of a malformed token, and UTC normalisation of emitted timestamps.
- [ ] T029 Permission & Audit - Implement the audit writer that persists `audit_event` inside the caller's transaction in `apps/api/src/gov/api/application/audit/write_audit.py`. Deliverable: atomic audit writes. Verify: an integration test asserts a failing state change writes no audit row and a committed change always has one.
- [ ] T030 Automated Testing - Build the Schemathesis contract-test harness that consumes `specs/001-agent-governance-platform/contracts/openapi.yaml` in `apps/api/tests/contract/`. Deliverable: automated conformance checks. Verify: the harness runs against the application and reports conformance for every implemented endpoint.
- [ ] T031 Automated Testing - Build testcontainer fixtures for PostgreSQL, Redis, OPA and Vault in `apps/api/tests/conftest.py`. Deliverable: hermetic integration environment. Verify: `pytest --collect-only` succeeds and a sample test boots all four containers.
- [ ] T032 Automated Testing - Build the security test harness that enumerates role-by-endpoint pairs and asserts deny-by-default in `apps/api/tests/security/`. Deliverable: repeatable authorization verification. Verify: the harness fails when a deliberate permission is removed and names the offending pair.
- [ ] T033 Infrastructure - Implement the worker skeleton with the outbox relay and Redis Streams publisher in `services/worker/src/gov/worker/`. Deliverable: asynchronous event delivery. Verify: an integration test asserts one published event is delivered exactly once and duplicate delivery is deduplicated on `event_id`.
- [ ] T034 Infrastructure - Implement the idempotent seed command for built-in roles, a demo organisation, an administrator and one demo account per role in `apps/api/src/gov/api/infrastructure/seed.py`. Deliverable: reproducible fixtures for manual validation. Verify: `make seed` run twice leaves row counts unchanged.
- [ ] T035 Automated Testing - Build the organisation-isolation suite asserting cross-tenant reads return no rows at both application and database level in `apps/api/tests/security/test_isolation.py`. Deliverable: FR-036 and SC-010 verification. Verify: the suite passes with two seeded organisations and fails if an RLS policy is dropped.

**Checkpoint**: Foundation ready. Every later phase can now proceed, and the P1 stories can be staffed in parallel.

---

## Phase 3: User Story 1 - Register and Govern Agents and Tools (Priority: P1)

**Goal**: an authorised user registers Agents, their versions, Tools, declared
permissions and risk levels, with ownership and lifecycle status, and the
registry rejects incomplete or duplicate entries.

**Independent Test**: register an Agent, add two versions, register two Tools
with permissions and risk levels, retire one version, and confirm the inventory
is correct while duplicates and incomplete entries are refused with actionable
messages (quickstart V1 and V2).

### Tests for User Story 1

- [ ] T036 [P] [US1] Automated Testing - Author contract tests for the registry endpoints (`POST/GET/PATCH /agents`, `GET/POST /agents/{id}/versions`, `POST/GET/PATCH /tools`) from `contracts/openapi.yaml` in `apps/api/tests/contract/test_registry_contract.py`. Deliverable: conformance tests for the registry surface. Verify: Schemathesis exercises every registry operation and reports conformance once T042 lands.
- [ ] T037 [US1] Automated Testing - Author the integration test scaffold for US1 acceptance scenarios 1 to 5 in `apps/api/tests/integration/test_registry.py`. Deliverable: failing-first tests for the registry story. Verify: tests run and fail for the expected reason before implementation.

### Implementation for User Story 1

- [ ] T038 [P] [US1] Data Model - Registry schema, split across two revisions because the Agent Registry and the Tool Registry are separate governance domains: `apps/api/migrations/versions/0003_registry.py` creates `agent` and `agent_version` (with `agent (organisation_id, name) UNIQUE`, `agent_version (agent_id, version) UNIQUE`, and the partial unique index allowing exactly one `released` version per agent), and `apps/api/migrations/versions/0004_tool_registry.py` creates `tool` and `tool_permission` (with `tool (organisation_id, name) UNIQUE`, the `risk_level` enum `low|medium|high|critical`, and the partial index on high-risk tools). Both migrations carry `organisation_id` with row-level security and composite foreign keys, and neither grants `DELETE` to the application role. Deliverable: registry schema. Verify: `alembic upgrade head` and `alembic check` are clean, and a duplicate insert raises a constraint violation. Note: this revision is 0003, not 0002, because T119's `0002_audit_event` must land first so that T048's `audit_*` indexes resolve against an existing table. Note: the revision chain now runs 0001_identity, 0002_audit_event, 0003_registry, 0004_tool_registry; the `model_id` foreign key on `agent_version` is deliberately deferred to the Model Registry revision, because the target table does not exist yet.
- [X] T039 [P] [US1] Data Model - Implement registry domain entities and validation in `apps/api/src/gov/api/domain/registry/`: name length 1 to 200, semantic-version format for `version`, `owner_user_id` required, `risk_basis` required, and a Tool permission list with at least one entry. Deliverable: validated domain model. Verify: unit tests cover each rule, including a submission missing an owner and a submission missing a risk level.
- [ ] T040 [US1] Backend API - Implement tenant-scoped registry repositories in `apps/api/src/gov/api/infrastructure/repositories/registry.py`. Deliverable: persistence layer honouring RLS. Verify: integration tests assert a query issued in one organisation never returns another organisation's Agents or Tools.
- [X] T041 [US1] Backend API - Implement registry use cases (create, update and retire Agent; add version; release a version; create and update Tool) in `apps/api/src/gov/api/application/registry/`, emitting an audit event via T029 and a domain event via T020 per mutation, and rejecting duplicate registrations atomically. Deliverable: registry application layer. Verify: integration tests assert an audit row and an outbox row for each successful mutation, and no rows at all for a rejected one.
- [X] T042 [US1] Backend API - Implement registry routers and Pydantic request and response schemas in `apps/api/src/gov/api/interface/registry/` matching `contracts/openapi.yaml`. Deliverable: the registry HTTP surface. Verify: contract tests from T036 pass and a failed validation returns RFC 9457 problem details naming the offending field.
- [ ] T043 [US1] Permission & Audit - Wire authorization for the registry endpoints so `platform_administrator` and `agent_developer` may register and update, only `platform_administrator` may retire, and `auditor` and `security_compliance` are read-only, and enforce that a lapsed role assignment no longer grants its permission (constitution Principle V, time-bound grants). Deliverable: enforced registry permissions. Verify: the security harness from T032 reports the expected allow or deny outcome for every role on every registry route, and a test asserts an expired assignment grants nothing. Note: the retire split follows the implemented permission matrix, correcting an earlier conflict between this task and the code.
- [ ] T044 [P] [US1] Frontend UI - Generate the typed API client from `contracts/openapi.yaml` into `apps/web/src/lib/api/` using `npm run generate:api`. Deliverable: shared frontend client. Verify: generation succeeds, `tsc --noEmit` passes, and a smoke test fetches `/agents` against the running API.
- [ ] T045 [US1] Frontend UI - Build the registry feature in `apps/web/src/features/registry/`: Agent list and detail with version history, Tool list with risk level and permissions, create and edit forms, and inline validation errors sourced from problem details. Deliverable: working registry screens. Verify: Vitest component tests pass and the manual walkthrough reproduces quickstart V1 and V2.

**Checkpoint**: User Story 1 is complete and independently demonstrable; the registry is populated and auditable, but nothing is governed at invocation time yet.

---

## Phase 4: User Story 2 - Policy-Controlled Tool Invocation with Audit Trail (Priority: P1)

**Goal**: policies decide whether an Agent may invoke a Tool, every attempt is
judged deterministically and deny-by-default, and every attempt produces an
audit record naming the deciding policy version.

**Independent Test**: publish an allow policy for one Agent and Tool pair,
attempt a permitted and a non-permitted invocation, and confirm the first
proceeds, the second is refused with a stated reason, and both are recorded
(quickstart V3, V4, V9, V10).

### Tests for User Story 2

- [ ] T046 [P] [US2] Automated Testing - Author contract tests for the policy endpoints (`POST/GET /policies`, `POST /policies/{id}/versions`, `POST /policy-evaluations`) and `POST /internal/invocations` in `apps/api/tests/contract/test_policy_contract.py`. Deliverable: conformance tests for the policy surface. Verify: Schemathesis covers every operation and reports conformance once T051 and T056 land.
- [ ] T047 [P] [US2] Automated Testing - Author the integration test scaffold for US2 scenarios 1 to 4 in `apps/api/tests/integration/test_policy_invocation.py`. Deliverable: failing-first tests for the enforcement story. Verify: tests run and fail for the expected reason before implementation.

### Implementation for User Story 2

- [ ] T048 [P] [US2] Data Model - Migration `apps/api/migrations/versions/0003_policy_invocation.py` creating `policy`, `policy_version`, `agent_tool_grant`, `invocation` and `policy_judgement`, with `policy_version (policy_id, version_number) UNIQUE`, `invocation (organisation_id, idempotency_key) UNIQUE`, and the indexes `invocation_org_time_idx`, `invocation_pending_approval_idx`, `policy_lookup_idx`, `audit_org_time_idx`, `audit_org_seq_uq`, `audit_actor_idx`, `audit_target_idx`, `audit_correlation_idx` and `audit_detail_gin`. Deliverable: policy and invocation schema. Verify: `alembic check` is clean and an integration test proves the idempotency uniqueness constraint rejects a second identical key.
- [X] T049 [P] [US2] Data Model - Implement the policy domain model and decision-input assembly in `apps/api/src/gov/api/domain/policy/`: build the exact evaluation input (actor, Agent version, Tool, environment, time window, risk level and resolved grants) that the policy bundle consumes, plus the FR-016 risk rules and risk escalation. The allow/deny resolution itself stays in `deploy/policy/policy.rego` as the single source of truth (ADR-0005); duplicating it here would create a second, silently divergent authority for the platform's most security-critical decision. Deliverable: policy domain logic. Verify: unit tests assert the assembled input matches the shape the Rego bundle reads, that unexpected policy attributes cannot influence the input, that a malformed policy effect is rejected, and that high or critical risk always requires approval; deny-by-default, deny-wins and matched-version retention are verified against the bundle by `opa test` (T010).
- [ ] T050 [US2] Permission & Audit - Implement the OPA client and bundle publishing from policy versions in `apps/api/src/gov/api/infrastructure/opa/`, recording the published `bundle_digest` on each judgement. Deliverable: policy evaluation integration. Verify: an integration test publishes a version and asserts the resulting judgement cites its `bundle_digest`.
- [ ] T051 [US2] Backend API - Implement Policy Center use cases and routers in `apps/api/src/gov/api/application/policy/` and `apps/api/src/gov/api/interface/policy/`: create a draft policy, publish an immutable version after validating the Rego, list policies, and dry-run a decision. Deliverable: the policy HTTP surface. Verify: invalid Rego returns 422 and publishes nothing, while valid Rego publishes a version whose number is monotonic per policy.
- [ ] T052 [P] [US2] Infrastructure - Implement the minimal isolated runner with a shared sandbox class and a tool adapter interface in `services/runner/src/gov/runner/`, rejecting any dispatch that does not originate from the gateway workload identity. Deliverable: isolated tool execution. Verify: an integration test dispatches through the gateway to a stub adapter successfully and asserts a direct call is rejected.
- [X] T053 [US2] Permission & Audit - Implement the MCP gateway enforcement chain in `services/gateway/src/gov/gateway/`, applying authN, authZ, policy, risk classification, approval, pre-execution audit and dispatch in that fixed order and failing closed when any dependency is unreachable (the post-execution audit stage is added by T055). Deliverable: the enforcement point described in `contracts/mcp-gateway.md`. Verify: gateway unit tests assert the stage order, and a test with OPA stopped yields a denial carrying `degraded_mode: true`.
- [ ] T054 [US2] Permission & Audit - Implement gateway idempotency handling so a replay of an existing key returns the original outcome, including a `pending_approval` outcome, without creating a second record. Deliverable: at-most-once execution. Verify: an integration test issues the same key twice and asserts one `invocation` row and an identical response.
- [ ] T055 [US2] Permission & Audit - Implement audit emission on the invocation path in `services/gateway/src/gov/gateway/audit.py`, writing a pre-execution event and a post-execution event with outcome and reason for both allowed and denied invocations. Deliverable: complete invocation auditing. Verify: integration tests assert two audit rows for a successful invocation and one for a denial, each carrying a reason when the outcome is not a success.
- [ ] T056 [US2] Backend API - Implement `POST /internal/invocations`, recording the gateway's already-made decision with idempotent replay semantics and exposing it only to the gateway. Deliverable: the internal recording endpoint. Verify: a contract test passes and a replayed request returns the original invocation rather than creating a second.
- [ ] T057 [US2] Automated Testing - Complete the US2 integration suite: allow path, deny-by-default path, deny-wins conflict path with both policies recorded, and audit-record content assertions, in `apps/api/tests/integration/test_policy_invocation.py`. Deliverable: US2 scenario coverage. Verify: the suite is green.
- [ ] T058 [US2] Automated Testing - Implement the fail-closed test: stop OPA, issue an invocation, assert a denial carrying `degraded_mode: true` with a recorded reason, then restart OPA and assert normal service resumes, in `apps/api/tests/integration/test_fail_closed.py`. Deliverable: FR-038 and quickstart V9 coverage. Verify: the test is green and fails if the gateway is changed to allow on error.
- [ ] T059 [US2] Frontend UI - Build the Policy Center screens in `apps/web/src/features/policy/`: policy list, editor with Rego text and validation feedback, version publishing with digest display, and a dry-run panel showing the decision and matched policies. Deliverable: working policy screens. Verify: component tests pass and a manual dry-run reproduces V3 and V4.
- [ ] T060 [US2] Frontend UI - Build the audit trail view in `apps/web/src/features/audit/` with filters for time range, actor, Agent, Tool, outcome and correlation id, plus a detail panel showing the chain for one operation. Deliverable: reconstructable audit view. Verify: component tests pass and the manual walkthrough reproduces V10.

**Checkpoint**: User Story 2 is complete; every tool invocation is now governed by policy and recorded, which is the platform's central capability.

---

## Phase 5: User Story 3 - Manual Approval for High-Risk Operations (Priority: P1)

**Goal**: high-risk invocations cannot execute until a designated approver
records an explicit, attributable decision, and rejected or expired requests
never execute.

**Independent Test**: classify a Tool as high risk, confirm the invocation is
held, approve one request and reject another, and confirm that only the approved
one executes with a fully recorded decision (quickstart V5 to V8).

### Tests for User Story 3

- [ ] T061 [P] [US3] Automated Testing - Author contract tests for the approval endpoints (`GET /approval-requests`, `GET /approval-requests/{id}`, `POST /approval-requests/{id}/decisions`) in `apps/api/tests/contract/test_approval_contract.py`. Deliverable: conformance tests for the approval surface. Verify: Schemathesis covers every operation and reports conformance once T065 lands.
- [ ] T062 [P] [US3] Automated Testing - Author the integration test scaffold for US3 scenarios 1 to 5 and quickstart V5 to V8 in `apps/api/tests/integration/test_approval.py`. Deliverable: failing-first tests for the approval story. Verify: tests run and fail for the expected reason before implementation.

### Implementation for User Story 3

- [ ] T063 [P] [US3] Data Model - Migration `apps/api/migrations/versions/0004_approval.py` creating `approval_request` and `approval_decision`, with `approval_request (organisation_id, invocation_id) UNIQUE`, `required_approvals` defaulting to 1, `allow_self_approval` defaulting to false, a required `expires_at`, the index `approval_pending_idx`, and no `UPDATE` or `DELETE` grant on `approval_decision`, mirroring T019. Deliverable: approval schema. Verify: `alembic check` is clean, and an integration test asserts a duplicate approval for one invocation is rejected and a decision row cannot be modified or deleted.
- [X] T064 [P] [US3] Data Model - Implement the approval state machine in `apps/api/src/gov/api/domain/approval/`: `pending` to `approved`, `rejected`, `expired` or `cancelled`, closing only when the count of distinct approving users reaches `required_approvals`. Deliverable: approval domain logic. Verify: unit tests cover every valid transition, refuse every invalid one, and enforce the distinct-approver rule.
- [X] T065 [US3] Backend API - Implement approval use cases and routers in `apps/api/src/gov/api/application/approval/` and `apps/api/src/gov/api/interface/approval/`: list and get requests with evidence, and record a decision with a mandatory reason, refusing self-approval by default. Deliverable: the approval HTTP surface. Verify: integration tests assert 403 for self-approval, 409 when the request is no longer pending, and a persisted immutable decision otherwise.
- [ ] T066 [US3] Infrastructure - Implement the expiry worker job in `services/worker/src/gov/worker/approval_expiry.py`, transitioning pending requests past `expires_at` to `expired` and emitting the corresponding event. Deliverable: bounded approval windows. Verify: a test with a short window asserts the transition, the emitted event, and that the invocation never executes.
- [ ] T067 [US3] Permission & Audit - Implement gateway approval hold and resume in `services/gateway/src/gov/gateway/approval.py`, and re-evaluate an in-flight request when a Tool's risk level rises. Deliverable: enforced high-risk gating. Verify: tests assert no high-risk execution without an approval record, and that raising a Tool's risk level while a request is pending forces re-evaluation instead of completion.
- [ ] T068 [US3] Frontend UI - Build the Approval Center in `apps/web/src/features/approval/`: pending queue showing age, requesting Agent and risk level, an evidence panel, and approve or reject actions with a mandatory reason. Deliverable: working approver experience. Verify: component tests pass and the manual walkthrough reproduces V5 to V8.
- [ ] T069 [US3] Automated Testing - Complete the US3 security suite in `apps/api/tests/security/test_approval_security.py`: approval authority separation, self-approval refusal, single-use approvals, expiry and replay protection. Deliverable: FR-004, FR-019 and FR-022 verification. Verify: `make test-security` is green and fails if the self-approval rule is disabled.

**Checkpoint**: the P1 governance loop is complete and the minimum viable product is demonstrable end to end.

---

## Phase 6: User Story 4 - Model Registry with Vendor and Usage Restrictions (Priority: P2)

**Goal**: models Agents rely on are registered with vendor and permitted or
prohibited uses, and prohibited use is reported as a violation.

**Independent Test**: register two models with different vendors and
restrictions, associate each with an Agent version, and confirm a prohibited use
is reported as a violation (spec US4 scenarios 1 to 3).

- [ ] T070 [P] [US4] Data Model - Migration `apps/api/migrations/versions/0005_model.py` creating `model` and `model_usage_restriction`, with `restriction_type` in `allowed|prohibited`, `dimension` in `scenario|data_class|region`, `model (organisation_id, name) UNIQUE`, and `reason` required when `restriction_type` is `prohibited`. Deliverable: model governance schema. Verify: `alembic check` is clean and an integration test rejects a `prohibited` restriction with no reason.
- [ ] T071 [US4] Backend API - Implement model registry use cases and routers in `apps/api/src/gov/api/application/model/` and `apps/api/src/gov/api/interface/model/`, including a usage-restriction check that reports a violation when a proposed use is prohibited or the model is withdrawn. Deliverable: model governance API. Verify: integration tests assert a violation report for a prohibited scenario and a refusal for a withdrawn model.
- [ ] T072 [US4] Permission & Audit - Wire authorization and audit for model registry changes so only `platform_administrator` writes and `agent_developer` may propose, with every mutation audited. Deliverable: enforced model permissions. Verify: the security harness reports the expected allow or deny per role, and an audit row exists for each accepted mutation.
- [ ] T073 [US4] Automated Testing - Implement US4 integration tests covering registration with restrictions, prohibited-use violation and withdrawn-model refusal in `apps/api/tests/integration/test_model_registry.py`. Deliverable: US4 scenario coverage. Verify: the suite is green and fails if the restriction check is bypassed.
- [ ] T074 [US4] Frontend UI - Build the model registry screens in `apps/web/src/features/registry/models/`: model list with vendor and status, create and edit form with allowed and prohibited restrictions, and violation feedback. Deliverable: working model screens. Verify: component tests pass and a prohibited use is surfaced in the UI.

**Checkpoint**: model governance is complete and independent of the release and evaluation phases.

---

## Phase 7: User Story 5 - Audit Investigation, Search and Export (Priority: P2)

**Goal**: an Auditor can search the audit trail by actor, Agent, Tool, outcome or
approval state, follow one operation end to end, and export the result.

**Independent Test**: generate allowed, denied and approved operations, then
reconstruct one governed operation from search results alone and export the same
result set (quickstart V10).

- [ ] T075 [P] [US5] Data Model - Migration `apps/api/migrations/versions/0006_audit_export.py` creating `audit_export` with a `filter` JSONB column, a status enum of `queued|running|ready|failed|expired`, and `expires_at` for download links. Deliverable: export tracking schema. Verify: `alembic check` is clean and an expired export cannot be downloaded.
- [ ] T076 [US5] Backend API - Implement audit search in `apps/api/src/gov/api/interface/audit/` with filters for time range, actor, Agent, Tool, outcome and correlation id, backed by the indexes from T048 and returning stable pagination. Deliverable: the audit query surface. Verify: integration tests assert each filter narrows results correctly and that a query never returns another organisation's events.
- [ ] T077 [US5] Backend API - Implement the audit export job in `services/worker/src/gov/worker/audit_export.py`, writing the result set to object storage and returning an expiring signed reference, with exported fields identical to the on-screen fields. Deliverable: export capability. Verify: an integration test asserts row-for-row parity between the on-screen result and the exported file.
- [ ] T078 [US5] Permission & Audit - Wire auditor permissions so `auditor` and `security_compliance` may search and export while other roles are refused, and audit every export request itself. Deliverable: enforced audit access. Verify: the security harness asserts a refusal for roles without audit permissions and an audit row for each export.
- [ ] T079 [US5] Automated Testing - Implement US5 integration tests covering outcome filtering, single-operation chain reconstruction and export parity in `apps/api/tests/integration/test_audit_search.py`. Deliverable: US5 scenario coverage. Verify: the suite is green and the reconstruction test fails if `correlation_id` propagation is broken.
- [ ] T080 [US5] Frontend UI - Extend the audit feature in `apps/web/src/features/audit/` with the full filter set, a per-operation chain view, and an export action with progress and download states. Deliverable: investigation UI. Verify: component tests pass and the manual walkthrough reproduces V10 including export.

**Checkpoint**: audit investigation is complete and can be demonstrated to an auditor independently of later phases.

---

## Phase 8: User Story 6 - Release Lifecycle: Release, Canary, Rollback, Decommission (Priority: P2)

**Goal**: a version is released gradually, promoted, rolled back when it
misbehaves and decommissioned, with every state change recorded.

**Independent Test**: release a version to a defined portion, promote it, roll it
back, and decommission it, confirming restoration of the previous governed
behaviour and a recorded reason for the rollback (spec US6 scenarios 1 to 4).

- [ ] T081 [P] [US6] Data Model - Migration `apps/api/migrations/versions/0007_release.py` creating `release` and `release_event`, with the partial unique index `release_active_uq` permitting only one non-terminal release per agent, and `reason` required on rollback events. Deliverable: release schema. Verify: `alembic check` is clean and an integration test rejects a second active release for the same agent.
- [X] T082 [US6] Data Model - Implement the release state machine in `apps/api/src/gov/api/domain/release/` covering `released` to `canary` to `promoted`, `canary` or `promoted` to `rolled_back`, and any state to `decommissioned`. Deliverable: release domain logic. Verify: unit tests cover every valid transition and refuse every invalid one.
- [ ] T083 [US6] Backend API - Implement release use cases and routers in `apps/api/src/gov/api/application/release/` and `apps/api/src/gov/api/interface/release/` for release, promote, rollback and decommission, refusing a release while a blocking evaluation failure is unresolved and restoring the previous governed configuration on rollback. Deliverable: the release HTTP surface. Verify: integration tests assert the refusal on a blocking failure and that rollback restores the previous version's policies, permissions and risk classification.
- [ ] T084 [US6] Infrastructure - Implement portion-based canary routing in `services/gateway/src/gov/gateway/canary.py` so only the configured share of traffic reaches the canary version, recording the decision. Deliverable: canary dispatch. Verify: a test issues many invocations and asserts the observed split approximates the configured portion and that each routing decision is auditable.
- [ ] T085 [US6] Permission & Audit - Wire authorization and audit for release transitions so only `platform_administrator` and `agent_developer` may act, and rollback and decommission always require a recorded reason. Deliverable: enforced release permissions. Verify: the security harness asserts refusals for other roles and an audit row with a reason for every rollback and decommission.
- [ ] T086 [US6] Automated Testing - Implement US6 integration tests covering canary release, promotion, rollback restoring behaviour within the SC-007 target, and decommission blocking further invocation, in `apps/api/tests/integration/test_release.py`. Deliverable: US6 scenario coverage. Verify: the suite is green, including a rollback timing assertion against the 15-minute target.
- [ ] T087 [US6] Frontend UI - Build the Release Center in `apps/web/src/features/release/`: version timeline, canary controls with portion setting, promote, and rollback and decommission dialogs requiring a reason. Deliverable: working release screens. Verify: component tests pass and the manual walkthrough exercises release, promote, rollback and decommission.

**Checkpoint**: release governance is complete and independently demonstrable.

---

## Phase 9: User Story 7 - Evaluation Center (Priority: P3)

**Goal**: an Agent version is evaluated against a versioned dataset and produces
a report showing passing and failing criteria, with datasets immutable once used.

**Independent Test**: run an evaluation against a dataset with known outcomes and
confirm per-criterion results, an overall outcome, and that the dataset can no
longer be modified in place (spec US7 scenarios 1 to 3).

- [ ] T088 [P] [US7] Data Model - Migration `apps/api/migrations/versions/0008_evaluation.py` creating `test_dataset`, `evaluation_task` and `evaluation_report`, with `test_dataset (organisation_id, name, version_number) UNIQUE`, a required `content_digest`, and `is_immutable` set once any task uses the dataset. Deliverable: evaluation schema. Verify: `alembic check` is clean and an integration test refuses an in-place change to an immutable dataset.
- [ ] T089 [US7] Backend API - Implement dataset creation (new version only), evaluation task creation and report retrieval in `apps/api/src/gov/api/application/evaluation/` and `apps/api/src/gov/api/interface/evaluation/`, matching `contracts/openapi.yaml`. Deliverable: the evaluation HTTP surface. Verify: contract tests pass and a duplicate dataset version returns 409.
- [ ] T090 [US7] Infrastructure - Implement evaluation execution in `services/worker/src/gov/worker/evaluation.py`, dispatching through the isolated runner and producing per-criterion observed-versus-expected results plus an overall outcome. Deliverable: evaluation engine. Verify: an integration test with a known dataset produces the expected pass and fail results and sets `blocking_failure` correctly.
- [ ] T091 [US7] Automated Testing - Implement US7 integration tests covering report generation, dataset immutability, report reproducibility after a new dataset version, and the release gate refusing a version with a blocking failure, in `apps/api/tests/integration/test_evaluation.py`. Deliverable: US7 scenario coverage. Verify: the suite is green and the release-gate test fails if FR-029 is not enforced.
- [ ] T092 [US7] Frontend UI - Build the Evaluation Center in `apps/web/src/features/evaluation/`: task creation, dataset version picker, and a report view highlighting failing criteria with observed versus expected values. Deliverable: working evaluation screens. Verify: component tests pass and a failing criterion is clearly attributed.

**Checkpoint**: evaluation is complete and wired into the release gate.

---

## Phase 10: User Story 8 - Governance Dashboard (Priority: P3)

**Goal**: a dashboard shows operational status, open risk events and governance
metrics, with every figure reconcilable against audit data.

**Independent Test**: with a known set of operations and approvals, confirm each
dashboard figure matches a manual count of the same source data (spec US8 and FR-034).

- [ ] T093 [P] [US8] Data Model - Implement the dashboard read model and its projection consumer in `services/worker/src/gov/worker/dashboard_projection.py`, fed from the outbox stream so reporting load never touches the enforcement path. Deliverable: a reconcilable projection. Verify: replaying the same events twice produces identical projection state.
- [ ] T094 [US8] Backend API - Implement `GET /dashboard/overview`, `GET /dashboard/metrics` and `GET /dashboard/risk-events` in `apps/api/src/gov/api/interface/dashboard/`, including invocation volume, denial rate, approval rate and approval latency. Deliverable: dashboard API. Verify: contract tests pass and metrics for a seeded period match the expected values.
- [ ] T095 [US8] Automated Testing - Implement the reconciliation test in `apps/api/tests/integration/test_dashboard.py`, asserting every dashboard figure equals a direct count over the corresponding audit records. Deliverable: FR-034 verification. Verify: the test is green and fails if the projection diverges from the audit data.
- [ ] T096 [US8] Frontend UI - Build the dashboard in `apps/web/src/features/dashboard/`: operational status panels, a risk event list linking to audit records, pending approvals with age, and metric charts. Deliverable: working dashboard. Verify: component tests pass and each figure links to a verifiable audit query.

**Checkpoint**: all eight user stories are functional and independently demonstrable.

---

## Phase 11: Polish and Cross-Cutting Concerns

**Purpose**: production readiness that spans stories.

- [ ] T097 Infrastructure - Author Helm charts in `deploy/helm/` for the control plane, gateway, runner and worker, including a distinct node pool and runtime class for high-risk sandboxes and external references to PostgreSQL, Redis, OPA, Vault and Keycloak. Deliverable: on-premises deployment. Verify: `helm template` renders without error and `helm lint` passes.
- [ ] T098 Infrastructure - Author the air-gapped installation bundle in `deploy/airgap/`: image mirroring manifest, offline installer script and operator instructions. Deliverable: egress-free installation. Verify: a dry run on a network-isolated host completes with no outbound request.
- [ ] T099 Permission & Audit - Implement the audit chain verifier job and wire it to `make audit-verify`, recomputing each organisation's chain and raising a risk event on any mismatch. Deliverable: tamper detection. Verify: the verifier reports a valid chain on clean data and raises a risk event when a row is deliberately altered in a test fixture.
- [ ] T100 Infrastructure - Author the backup and restore runbook and execute a restore drill, recording timings in `docs/runbooks/backup-restore.md`. Deliverable: rehearsed recovery. Verify: the drill restores a full environment, the recorded audit chain verifies after restore, and results are documented.
- [ ] T101 Automated Testing - Implement the k6 performance suite in `tests/perf/` covering policy decision p95, audit search p95, dashboard aggregate p95 and a burst of concurrent invocations. Deliverable: quantified performance. Verify: results are compared against the performance goals in plan.md and regressions are reported by the nightly job.
- [ ] T102 Automated Testing - Automate the full quickstart walkthrough V1 to V11 as a Playwright suite in `apps/web/tests/e2e/`, so the acceptance contract is machine-verified rather than manual. Deliverable: automated acceptance. Verify: `make test-e2e` is green and every quickstart scenario maps to at least one test.
- [ ] T103 Infrastructure - Add Prometheus and Grafana assets in `deploy/observability/` with alerts for policy denial rate, degraded-mode denials, approval latency, outbox lag and failed rollbacks. Deliverable: operational visibility. Verify: the alert rules load in Prometheus and each alert can be triggered in a test environment.
- [ ] T104 Permission & Audit - Update the threat model in `docs/runbooks/threat-model.md` with the Phase 0 sandbox findings and a recorded residual-risk statement. Deliverable: current risk posture. Verify: every security risk in plan.md appears with a mitigation status of mitigated, accepted or open.
- [ ] T105 Infrastructure - Author operator runbooks in `docs/runbooks/`, a policy style guide in `deploy/policy/README.md`, and contributor guidance in `AGENTS.md`. Deliverable: runtime development guidance referenced by the constitution. Verify: a new contributor can start the stack and run the test suite using only these documents.
- [ ] T106 Infrastructure - Perform the release-readiness review and record it in `docs/runbooks/release-readiness.md`: confirm all nine CI gates enforce on the release branch, dependency and container scans are clean, and no secret exists in tracked configuration. Deliverable: a release decision record. Verify: the release branch pipeline is green and the review outcome is recorded.

---

## Phase 12: Analysis Remediation Tasks

**Purpose**: tasks added after `$speckit-analyze` to close coverage gaps and
constitution alignment findings. Each task states its prerequisite so it can be
scheduled without renumbering the phases above.

- [X] T107 Permission & Audit - Implement sensitive-data redaction in `apps/api/src/gov/api/infrastructure/redaction.py` and wire it into logging, tracing, metrics labels and error serialisation, using the classification set from T026. Deliverable: FR-040 coverage (constitution Principle V). Verify: a test injects a classified value into a request and asserts it never appears in log records, spans, metric labels or problem details.
- [ ] T108 Data Model - Implement retention and deletion rules in `apps/api/src/gov/api/application/retention/` plus the scheduled job in `services/worker/src/gov/worker/retention.py`, archiving or deleting records per the configured period and auditing every action. Deliverable: FR-041 coverage (constitution, Enterprise Platform Constraints). Verify: with a short retention window a test asserts records are archived and the action audited, and a second test asserts audit records are never removed before their configured period.
- [ ] T109 Infrastructure - Declare availability and recovery service-level objectives in `deploy/observability/slo.yaml` and expose measured availability against them. Deliverable: FR-042 coverage (constitution, Enterprise Platform Constraints). Verify: the SLO definitions load, the dashboard reports measured availability against the declared target, and a simulated breach is visible.
- [ ] T110 Data Model - Migration `apps/api/migrations/versions/0009_risk_event.py` creating `risk_event` with `severity`, `source`, `status`, `audit_event_id`, `detected_at` and the index `risk_event_open_idx`, plus the service that raises events. Deliverable: data support for FR-033. Verify: `alembic check` is clean, and a test raises a risk event from a simulated audit chain mismatch and retrieves it through the dashboard query.
- [ ] T111 Automated Testing - Add a policy-propagation timing test in `apps/api/tests/integration/test_policy_propagation.py` asserting a published policy change is reflected in judgements for new invocations within the declared period. Deliverable: SC-006 and FR-015 verification. Verify: the test is green and fails if cache invalidation is removed. Prerequisite: T051.
- [ ] T112 Automated Testing - Add a judgement-immutability test in `apps/api/tests/integration/test_judgement_immutability.py` asserting that changing a Tool's risk level, permissions or a model's restrictions does not alter any previously recorded judgement or audit record. Deliverable: FR-010 verification. Verify: the test is green and fails if judgements are recomputed on read. Prerequisite: T041 and T055.
- [ ] T113 Automated Testing - Add an onboarding walkthrough in `apps/web/tests/e2e/onboarding.spec.ts` that registers an Agent, its version and its Tools and records elapsed time against the SC-004 target. Deliverable: SC-004 verification. Verify: the run reports an elapsed time and fails when the target is exceeded. Prerequisite: T045.
- [ ] T114 Automated Testing - Add an approval-throughput test in `apps/api/tests/integration/test_approval_latency.py` measuring decision latency and the share of requests decided within the configured window. Deliverable: SC-005 verification. Verify: the test reports both figures and fails when window compliance is missed. Prerequisite: T065.
- [ ] T115 Automated Testing - Add a role-journey test in `apps/web/tests/e2e/role-journeys.spec.ts` exercising the primary journey of each of the five roles and reporting completion. Deliverable: SC-009 verification. Verify: every role journey executes and the run reports pass or fail per role. Prerequisite: T045 and T068.
- [ ] T116 Permission & Audit - Raise risk events from every declared source in `apps/api/src/gov/api/application/risk/`: audit chain mismatch, failed rollback, approval anomaly (a request decided outside its window or by an ineligible approver) and fail-closed denial spikes, plus a manual-raise path for administrators, wiring them to the dashboard and to alerting. Deliverable: complete FR-033 risk-event sources matching the `risk_event.source` enum. Verify: each of the five sources produces a risk event in an integration test, and an alert fires for high and critical severities. Prerequisite: T110.
- [ ] T117 Data Model - Align the `tool_permission.action` enumeration with the API contract (`read`, `write`, `execute`, `approve`, `delete`) in the migration and the domain model. Deliverable: one canonical action set. Verify: the contract test rejects an action outside the enumeration. Prerequisite: T038.
- [X] T118 Data Model - Implement the FR-043 classification taxonomy (`public`, `internal`, `confidential`, `restricted`) in `apps/api/src/gov/api/domain/classification/` and apply it to tool permissions, model usage restrictions and stored sensitive fields, exposing it to the redaction layer in T107. Deliverable: FR-043 coverage and the prerequisite for T107. Verify: a test rejects an undeclared class, and a classified value stored under each class is redacted correctly by T107.

**Execution order note**: Phase 12 tasks were appended to preserve task IDs after
analysis. Their natural phases are: T107, T108 and T109 in Phase 2 (cross-cutting
foundation); T110 after T021; T111 after T051; T112 after T041 and T055; T113
after T045; T114 after T065; T115 after T045 and T068; T116 after T110; T117
after T038; T118 after T026. Schedule them at those points rather than strictly
after Phase 11.

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 0 (Spike)**: no dependencies; must complete before anything else because its outcome can change ADR-0003 and ADR-0005.
- **Phase 1 (Setup)**: depends on the Phase 0 gate; no dependencies on other phases.
- **Phase 2 (Foundational)**: depends on Phase 1; **blocks every user story**.
- **Phase 3 (US1)**: depends on Phase 2.
- **Phase 4 (US2)**: depends on Phase 2. Its dry-run and audit-view tasks use US1 test data but do not require US1 to be complete.
- **Phase 5 (US3)**: depends on Phase 2 and on the gateway established in US2 (T053).
- **Phases 6 to 10 (US4 to US8)**: each depends on Phase 2. US7 additionally depends on the release gate in US6 (T083) to enforce FR-029, and US8 depends on the outbox relay (T033).
- **Phase 11 (Polish)**: depends on the phases whose features it hardens. T097 and T098 may proceed once Phase 2 completes; T099 and T100 require US2 and US3.
- **Phase 12 (Analysis Remediation)**: each task depends on the prerequisite named in its own description; T107 to T110 may start once Phase 2 completes, and T111 to T117 depend on the implementation task they verify.

### User Story Dependencies

- **US1 (P1)**: independent once Phase 2 completes; no other story is required.
- **US2 (P1)**: independent of US1 in principle, but its end-to-end tests are far easier with registered Agents and Tools from US1.
- **US3 (P1)**: depends on the gateway from US2; it cannot be demonstrated without an invocation path.
- **US4 (P2)**: independent of US1 to US3; it shares only the registry UI shell.
- **US5 (P2)**: depends on audit capture from US2 for meaningful data.
- **US6 (P2)**: depends on the registry (US1) and, for its gate, on evaluation (US7) or an explicitly recorded exception.
- **US7 (P3)**: independent, and required by the release gate in US6.
- **US8 (P3)**: depends on the outbox and on audit and approval data from US2 and US3.

### Within Each User Story

- Tests are authored before implementation (T036 to T041, T046 to T050, T061 to T065).
- Data model precedes domain logic, which precedes repositories, use cases and routers.
- The backend precedes the frontend surface that consumes it, except for the generated API client, which depends only on the contract.
- A story is complete only when its integration tests and its quickstart scenarios pass.

---

## Parallel Execution Examples

**Phase 0**: all four spikes are independent and can run concurrently.

```text
Task: "T001 Measure OPA p95 decision latency"
Task: "T002 Prove the MCP gateway round trip with an audit write"
Task: "T003 Produce the sandbox escape checklist"
Task: "T004 Prove row-level-security isolation"
```

**Phase 1**: repository scaffolding in parallel after T005.

```text
Task: "T007 Author apps/web/package.json and vite.config.ts"
Task: "T008 Author the gateway, runner and worker packages"
Task: "T010 Author the OPA policy bundle scaffold"
Task: "T011 Author the Keycloak realm import"
```

**Phase 2**: foundation workstreams in parallel.

```text
Task: "T021 Audit hash-chain primitive"
Task: "T024 Role permission matrix"
Task: "T027 RFC 9457 error handling"
Task: "T033 Worker skeleton with outbox relay"
```

**Phase 4 (US2)**: independent workstreams.

```text
Task: "T048 Migration for policy and invocation tables"
Task: "T049 Policy domain model and conflict resolution"
Task: "T052 Isolated runner with the shared sandbox class"
```

**Phase 3 to 5 frontend**: the three P1 UI surfaces live in different feature
directories and can be built concurrently once their APIs land.

---

## Implementation Strategy

### MVP First (User Stories 1 to 3 only)

1. Complete Phase 0 (evidence gate) and Phase 1 (skeleton and CI).
2. Complete Phase 2 (foundation); nothing else can start until this is done.
3. Deliver US1, then US2, then US3.
4. **Stop and validate**: run quickstart V1 to V10 and the P1 acceptance scenarios.
5. The MVP is the runnable governance loop: register, decide, approve, record.

### Incremental Delivery

1. MVP (US1 to US3): the governed invocation loop.
2. Add US4 and US5: model governance and audit investigation.
3. Add US6: release control.
4. Add US7 and US8: evaluation and reporting.
5. Harden with Phase 11: on-premises deployment, performance and operational readiness.

Each increment leaves the previous increments working; no story depends on
partially built behaviour from a later story.

### Parallel Team Strategy

With three or four developers: one owns the gateway, policy and approval path
(T048 to T067), one owns the registry and release surfaces (T038 to T045, T081 to
T087), one owns the frontend across stories, and one owns testing, data integrity
and deployment (T030 to T035, T097 to T106). Cross-story work is safe because
stories touch different feature directories and the shared foundation is frozen
after Phase 2.

---

## Traceability and Coverage Check

This section answers the two checks requested: requirements that have no
implementation task, and tasks that have no requirement basis.

### Requirements mapped to tasks

| Requirement group | Tasks |
|-------------------|-------|
| FR-001 to FR-004 (roles, permissions, least privilege) | T024, T025, T032, T043, T072, T078, T085, T099 |
| FR-005 to FR-010 (registry, versions, tools, models, validation) | T038 to T043, T070 to T074, T112, T117 |
| FR-011 to FR-016 (policy, deny-by-default, conflicts, versioning, high-risk gating) | T048 to T051, T053, T057, T067 |
| FR-017 to FR-022 (approval requests, decisions, immutability, expiry, idempotency) | T054, T063 to T069 |
| FR-023 to FR-026 (audit capture, search, export, reconstruction) | T029, T055, T075 to T080 |
| FR-027 to FR-029 (evaluation, dataset immutability, release gate) | T088 to T092, T083 |
| FR-030 to FR-032 (release, canary, rollback, decommission) | T081 to T087 |
| FR-033 and FR-034 (dashboard and reconcilability) | T093 to T096 |
| FR-035 to FR-037 (private deployment, organisation isolation, runnable MVP) | T004, T018, T022, T035, T098 |
| FR-038 and FR-039 (exception processes and recorded reasons) | T053, T055, T058, T066, T086, T099 |
| FR-040 to FR-043 (redaction, retention and deletion, service-level objectives, data classification) | T107, T108, T109, T118 |
| SC-001 to SC-011 (measurable outcomes) | T057, T069, T079, T086, T095, T101, T102, T111, T113, T114, T115 |
| Constitution Principles I to X | T016 (layering), T015 (CI gates), T021 and T099 (audit integrity), T104 (threat model), T105 (runtime guidance), plus the ADRs referenced from plan.md |
| Plan Phase 0 exit criteria | T001 to T004 |

### Findings

- **No requirement is left without a task.** Every FR-001 to FR-042 maps to at
  least one task above. Every quickstart scenario maps to a test: V1 to V4 and
  V10 through T057 and T102; V5 to V8 through T069 and T102; V9 through T058;
  V11 through T035.
- **No task lacks a requirement basis.** Each task traces to a specification
  requirement, a plan phase, a quickstart scenario, a constitution principle or
  an ADR. The Phase 0 tasks (T001 to T004) trace to the Phase 0 exit criteria in
  plan.md and to ADR-0003, ADR-0005 and ADR-0006.
- **Formerly assumption-dependent tasks.** FR-022, FR-036 and FR-037 were
  resolved during review and are now normative in the specification. T063, T065
  and T069 implement the agreed approval rules parameterised by
  `required_approvals` and `allow_self_approval`, so a later policy change is
  configuration rather than code. T035 enforces organisation separation, which
  covers both the single-organisation and multi-organisation deployment cases.
- **Cross-story coupling to watch.** T083 (release gate) and T091 (release-gate
  test) reference each other across US6 and US7. Deliver T083 with a
  policy-driven gate so US7 can complete independently; do not hard-code the
  evaluation dependency into the release use case.

### Remediation applied after analysis

The `$speckit-analyze` pass identified coverage and constitution-alignment gaps.
The following were resolved in this revision:

- Constitution gaps C1 to C3 closed by adding FR-040 (redaction), FR-041
  (retention and deletion rules) and FR-042 (service-level objectives), each with
  a verifying task (T107 to T109).
- SC-004, SC-005, SC-006, SC-009 now have verification tasks (T113, T114, T111,
  T115), and FR-010 has an explicit immutability test (T112).
- The undefined `RiskClassification` reference was removed in favour of a
  derived risk level, and the missing `RiskEvent` entity was defined and tasked
  (T110, T116).
- The three `[NEEDS CLARIFICATION]` markers were resolved in the specification
  and the accepted defaults recorded in its Assumptions section.
- Terminology, enumeration and count inconsistencies across `events.md`,
  `openapi.yaml`, `data-model.md`, `plan.md` and `quickstart.md` were corrected.
- A second analysis pass (N1 to N10) rewrote the plan's carried-forward
  clarification section as resolved, fixed the data-classification taxonomy and
  the availability and recovery targets (FR-043, FR-042), aligned the `RiskEvent`
  API schema with the entity, added the destructive-migration rollback rule to
  T017, completed the risk-event sources in T116, and corrected the traceability
  rows.

---

## Notes

- `[P]` marks tasks that touch different files and have no dependency on an
  incomplete task.
- `[Story]` maps a task to a user story for traceability; Phase 0, Setup,
  Foundational and Polish tasks deliberately carry no story label.
- Commit after each task or logical group. Every task is scoped to be
  independently verifiable in one sitting, which is why each states its own
  verification method.
- No source code is created or modified by this command. These are task
  descriptions only; `$speckit-implement` executes them.
- Stop at any checkpoint to validate a story independently before proceeding.
- Avoid: vague tasks, same-file conflicts between parallel tasks, and
  cross-story dependencies that would break independent delivery.

---

## Phase 13: Convergence

**Purpose**: work identified by `$speckit-converge` that no existing task covers.
Appended without modifying, renumbering or reordering any earlier task.

- [ ] T119 Data Model - CRITICAL: add the missing migration that creates the `audit_event` table in `apps/api/migrations/versions/` per FR-023 and FR-024: `organisation_id`, `sequence`, `event_type`, `actor_type`, `actor_id`, `action`, `target_type`, `target_id`, `outcome`, `reason`, `detail` (JSONB), `correlation_id`, `occurred_at`, `recorded_at`, `prev_hash`, `entry_hash`, with the unique index on (`organisation_id`, `sequence`), the RLS policy, and the append-only grant model from T019 (missing). Deliverable: the table that the audit writer (T029), the audit indexes named in T048, audit search (T076), export (T077) and the chain verifier (T099) all depend on, and which no task previously created. Verify: `alembic upgrade head` creates the table; every `audit_*` index in T048 resolves against it; an integration test asserts the application role cannot UPDATE or DELETE a row.
- [ ] T120 Automated Testing - Make CI install and run every component's test suite rather than only the control plane, in `.github/workflows/ci.yml` per Constitution Principle VIII (partial). Deliverable: gates that execute the gateway, runner and worker suites, which currently never run in CI even though the gateway suite exists and passes. Verify: the workflow installs each service with its `[dev]` extras and runs `pytest` for `apps/api`, `services/gateway`, `services/runner` and `services/worker`; a deliberate failure in the gateway suite blocks the pipeline.
- [X] T121 Infrastructure - Fix the `seed` and `audit-verify` targets in `Makefile`, which currently expand to `python -m python -m gov...` because `API_PY := python -m` is followed by a literal `python -m`, making both targets unrunnable per the plan's development environment section (contradicts). Deliverable: working developer entry points. Verify: `make -n seed` and `make -n audit-verify` print a single `python -m ...` invocation, and both run once their target modules exist (T034, T099).
- [X] T122 Infrastructure - Add the runner HTTP entry point `services/runner/src/gov/runner/app.py` exposing the liveness probe its container image already declares, per the plan's `services/runner` structure (missing). Deliverable: a startable runner process. Verify: `uvicorn gov.runner.app:app` starts and `/healthz` returns 200; the image CMD resolves.
- [X] T123 Infrastructure - Add the worker entry point `services/worker/src/gov/worker/main.py` that starts the job loop, per the plan's `services/worker` structure (missing). Deliverable: a startable worker process. Verify: `python -m gov.worker.main` starts without import errors and exits cleanly on a termination signal; the image CMD resolves.
- [X] T124 Backend API - Implement the gateway's inbound invocation route in `services/gateway/src/gov/gateway/routes.py`, exposing the request and response shapes, status codes and guarantees defined in `contracts/mcp-gateway.md` on top of the enforcement pipeline (missing). Deliverable: the interface Agents actually call, which no task previously created. Verify: contract tests cover the documented statuses (200 allowed, 200 denied, 202 pending approval, 403, 404, 409, 503) and a denied invocation returns the recorded matched policy versions.
- [ ] T125 Frontend UI - Add the SPA entry point `apps/web/index.html` and `apps/web/src/main.tsx` with the router and provider shell described in the plan's `apps/web` structure, so the configured Vite build has something to build (missing). Deliverable: a buildable SPA shell. Verify: `npm ci && npm run build` succeeds and the dev server serves the shell.
- [X] T126 Infrastructure - Provide a documented, git-ignored bootstrap step that creates `deploy/compose/secrets/postgres_password` before the stack is started, per the plan's development environment section (missing). Deliverable: a startable development stack; the secret value must never be committed, in line with Constitution Principle V. Verify: the documented command creates the file, `deploy/compose/secrets/` is ignored by `.gitignore`, and `docker compose up` reaches healthy without a committed password.
- [X] T127 Frontend UI - Reconcile the generated API client output path so `apps/web/package.json` `generate:api`, `libs/contracts/README.md` and T044 all name the same destination for the generated TypeScript types per T044 (contradicts). Deliverable: one agreed output location, so the client is generated where the SPA imports it. Verify: `npm run generate:api` writes the types to the agreed path, `tsc --noEmit` passes, and the three artifacts agree.
- [ ] T128 Infrastructure - Retro-fit a task reference for the container images `apps/api/Dockerfile`, `services/gateway/Dockerfile`, `services/runner/Dockerfile` and `services/worker/Dockerfile`, which exist in the codebase but are called for by no task, per the plan's deployment decision (unrequested). Deliverable: traceability for the images the Compose stack builds. Verify: `docker build` succeeds for each image once T122 and T123 land, and the task referencing them is present in this list.
- [ ] T129 Infrastructure - Retro-fit a task reference for `services/gateway/src/gov/gateway/app.py`, the gateway process and liveness endpoint, which exists in the codebase but is called for by no task, per T053's gateway component (unrequested). Deliverable: traceability for the gateway process entry point. Verify: the file is referenced by a task in this list, and its health probe is exercised by the CI gate added in T120.
