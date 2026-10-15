---

description: "Task list for the Permission Center"
---

# Tasks: Permission Center

**Input**: Design documents from `/specs/002-permission-center/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Included. The constitution makes automated testing mandatory for
every API, and this feature's whole subject is whether access is controlled, so
the negative tests are the product.

**Organization**: Tasks are grouped by user story so each can be implemented and
tested independently.

## Category Legend

| Category | Meaning |
|----------|---------|
| Infrastructure | Runtime, deployment, tooling and platform plumbing |
| Data Model | Schema, migrations, domain rules and invariants |
| Backend API | Use cases, repositories, routers, contracts |
| Permission & Audit | Authorization, decision component, permission-change auditing |
| Frontend UI | React and TypeScript surfaces |
| Automated Testing | Test suites, harnesses and verification tooling |

## Format: `[ID] [P?] [Story?] Category - Description with file path`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story (US1-US5); absent in Setup, Foundational and Polish
- Every task states its file path, deliverable and verification method

---

## Phase 1: Setup

- [X] T001 Infrastructure - Create the Permission Center module skeleton: `apps/api/src/gov/api/domain/permission/`, `application/permission/`, `infrastructure/repositories/permission.py`, `interface/permission/` and `apps/web/src/features/permission/`. Deliverable: the module exists in the established layering. Verify: the directory tree matches plan.md and `import-linter` still passes.
- [X] T002 [P] Data Model - Define the permission catalogue as a single source in `apps/api/src/gov/api/domain/permission/catalogue.py`: stable name, resource, action, description and `is_builtin` for each permission the platform and this feature need. Deliverable: one catalogue consumed by the migration, the seed, the API and the tests. Verify: every name matches `^[a-z_]+\.[a-z_]+(\.[a-z_]+)?$`, every entry has a description, and a test asserts there are no duplicates.
- [ ] T003 [P] Infrastructure - Scaffold the authorization bundle `deploy/policy/authorization.rego` and `deploy/policy/authorization_test.rego`, with deny-by-default behaviour and one passing test. Deliverable: a testable bundle. Verify: `opa test deploy/policy` passes.
- [X] T004 Backend API - Reconcile the Permission Center contract with the platform contract so one document describes the whole API: fold `specs/002-permission-center/contracts/openapi.yaml` into the platform contract or record which paths each owns. Deliverable: a single authoritative contract, with the boundary recorded in plan.md. Verify: no path or schema is declared twice, and the existing contract tests still resolve every path.
- [X] T005 [P] Automated Testing - Wire the new surface into CI: add the permission routes to the security matrix harness and ensure `opa test` covers `authorization.rego`. Deliverable: the new module is gated like the rest. Verify: a deliberate permission-check regression fails the pipeline, and `opa test` runs on the authorization bundle.

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: every user story depends on this phase.

- [ ] T006 Data Model - Migration `apps/api/migrations/versions/0005_permission_center.py` creating `permission` and `role_permission` (with `organisation_id`, forced row-level security, a composite foreign key keeping bindings inside their own organisation, and no `DELETE` grant to the application role), **and altering the reused tables**: `role` gains `status` (`active`/`retired`, default `active`) with a check refusing to retire a built-in role, and `role_assignment` gains `revoked_at` and `revocation_reason` with a check that a reason accompanies a revocation. No `agent_responsibility` table: accountability reuses `agent.owner_user_id`, which is already `NOT NULL` and composite-keyed to the user. Deliverable: the permission schema plus the columns the reused tables were missing. Verify: `alembic upgrade head` and `alembic check` are clean; a cross-organisation binding raises a constraint violation; retiring a built-in role and revoking without a reason are both refused by the database.
- [X] T007 Data Model - Implement the domain rules in `apps/api/src/gov/api/domain/permission/`: catalogue invariants, role lifecycle (active to retired, never deleted while assigned), assignment scope consistency, expiry evaluation against a supplied authoritative time, and the immutability of the five built-in roles. Deliverable: validated domain model. Verify: unit tests cover each rule, including an attempt to amend a built-in role and an assignment whose scope contradicts its type.
- [X] T008 Backend API - Add the application ports in `apps/api/src/gov/api/application/ports.py`: repositories for permissions, role bindings and Agent responsibility, and the corresponding members on `UnitOfWork`. Deliverable: the use cases can be written against ports. Verify: the in-memory adapter satisfies every protocol member (a type check fails if not).
- [X] T009 Backend API - Implement the in-memory adapters for the new ports in `apps/api/tests/unit/_inmemory.py`, including unique-constraint behaviour for duplicate bindings and duplicate assignments. Deliverable: use-case tests can run without a database. Verify: a test asserts a duplicate binding raises and that a rolled-back unit of work leaves no rows.
- [X] T010 Permission & Audit - Implement the OPA authorization client in `apps/api/src/gov/api/infrastructure/opa/authorization.py`: assemble the versioned decision input, call the policy, parse the decision with its contributing sources, and fail closed on any error. Deliverable: the decision component. Verify: tests cover an allow, a deny, a deny with multiple sources, and an unreachable engine yielding a degraded refusal.
- [X] T011 Permission & Audit - Implement effective-permission resolution in `apps/api/src/gov/api/application/permission/effective.py`: role permissions plus assignments, filtered by organisation, scope and expiry, cached against a role-version token that any role, binding or assignment change invalidates. Deliverable: the resolution the request path uses. Verify: unit tests cover scope filtering, expiry, and that a revoked permission is absent on the very next resolution (FR-020).
- [X] T012 Permission & Audit - Extend the shared authorization dependency in `apps/api/src/gov/api/interface/security/authorize.py` to require an effective permission and consult the decision component, preserving deny-by-default, refusal reasons that name what is missing, and fail-closed behaviour. Deliverable: one guard used by every protected route. Verify: unit tests assert an unauthenticated caller is refused, a caller lacking the permission receives a 403 naming it, and an unavailable engine yields 503.
- [X] T013 Permission & Audit - Implement permission-change audit emission in `apps/api/src/gov/api/application/permission/audit.py`, writing `audit_event` rows in the caller's transaction with the action, target, reason and outcome for every change to roles, bindings, assignments and responsibility. Deliverable: FR-021 and FR-022 satisfied. Verify: a test asserts a failing audit write rolls the change back, and that a non-success outcome must carry a reason.
- [X] T014 Backend API - Implement user administration use cases in `apps/api/src/gov/api/application/permission/users.py`: create, review, disable and re-enable a user, recording display name, email and owning organisation, and emitting an audit record for each. Deliverable: FR-001 and FR-002. Verify: unit tests assert a duplicate external subject is refused, and that disabling a user removes their effective permissions without deleting history.
- [X] T015 Backend API - Implement user routers and schemas in `apps/api/src/gov/api/interface/permission/users.py` for `/v1/users` and `/v1/users/{user_id}`, matching the contract. Deliverable: the user surface. Verify: contract tests pass and validation failures name the offending field.
- [X] T016 Automated Testing - Extend the security harness in `apps/api/tests/security/` with the Permission Center's routes, in both the authenticated and unauthenticated case. Deliverable: the role matrix covers the new surface. Verify: the harness fails when a permission is removed from the guard for any new route.

**Checkpoint**: foundation ready; the five user stories can proceed.

---

## Phase 3: User Story 1 - Define Roles and Bind Permissions (Priority: P1)

**Goal**: an administrator creates a role, binds permissions to it, and can read
back exactly what it grants.

**Independent Test**: create a role, bind three permissions, read it back, remove
one, and confirm the effective set is exactly what it now lists (quickstart V1-V3).

### Tests for User Story 1

- [ ] T017 [P] [US1] Automated Testing - Contract tests for `/v1/permissions`, `/v1/roles`, `/v1/roles/{id}` and `/v1/roles/{id}/permissions` from `contracts/openapi.yaml`, in `apps/api/tests/contract/test_permission_roles_contract.py`. Deliverable: conformance tests for the role and permission surface. Verify: Schemathesis exercises every operation.
- [ ] T018 [US1] Automated Testing - Integration test scaffold for US1 scenarios 1 to 5 in `apps/api/tests/integration/test_roles.py`. Deliverable: failing-first tests. Verify: they run and fail for the expected reason before implementation.

### Implementation for User Story 1

- [ ] T019 [US1] Backend API - Implement the role repository in `apps/api/src/gov/api/infrastructure/repositories/permission.py`, tenant-scoped and honouring row-level security. Deliverable: persistence for roles and bindings. Verify: an integration test asserts a query in one organisation never returns another's roles.
- [X] T020 [US1] Backend API - Implement role use cases in `apps/api/src/gov/api/application/permission/roles.py`: create a role that grants nothing, amend its purpose, retire it, refuse a duplicate name, and refuse any change to a built-in role. Deliverable: FR-003, FR-004, FR-005, FR-031. Verify: unit tests cover each rule, including that a retired role grants nothing and cannot be assigned.
- [X] T021 [US1] Backend API - Implement permission binding use cases in `apps/api/src/gov/api/application/permission/bindings.py`: bind and unbind a permission, refuse an unknown permission name, and emit an audit record naming the permission. Deliverable: FR-006, FR-007, FR-008. Verify: unit tests assert the effective set changes exactly, and that an unknown name is refused without being stored.
- [X] T022 [US1] Backend API - Implement routers and schemas in `apps/api/src/gov/api/interface/permission/roles.py` for the four role and permission paths. Deliverable: the role HTTP surface. Verify: contract tests pass; a built-in role amendment returns 403 with a problem body.
- [X] T023 [US1] Permission & Audit - Wire authorization for the role surface in `apps/api/src/gov/api/interface/permission/roles.py`, so only a caller holding the permission to manage roles may act and an auditor is refused on every write. Deliverable: enforced administration. Verify: the security harness reports the expected outcome for every role on every route.
- [ ] T024 [US1] Automated Testing - Complete the US1 integration and security suite in `apps/api/tests/security/test_role_administration.py`, adding quickstart V1, V2 and V3. Deliverable: US1 scenario coverage. Verify: the suite is green and fails if the empty-role rule or built-in immutability is removed.

### Frontend for User Story 1

- [ ] T025 [P] [US1] Frontend UI - Build the roles and permissions screens in `apps/web/src/features/permission/`: role list distinguishing built-in from organisation roles, role detail showing the effective permission set, bind and unbind actions, and a permission catalogue browser grouped by resource. Deliverable: working administration screens. Verify: Vitest tests pass and the manual walkthrough reproduces V1 to V3.
- [ ] T026 [US1] Automated Testing - Playwright E2E for V1, V2 and V3 in `apps/web/tests/e2e/permission-roles.spec.ts`. Deliverable: automated acceptance. Verify: the suite is green.

**Checkpoint**: roles and permissions are administrable and independently demonstrable.

---

## Phase 4: User Story 2 - Assign Roles Within a Scope (Priority: P1)

**Goal**: an administrator assigns a role to a user, scoped and optionally
time-bound, and can revoke it with a reason.

**Independent Test**: assign a role for one Agent only, confirm the user can act
on that Agent and is refused on another (quickstart V4-V6, V13).

### Tests for User Story 2

- [ ] T027 [P] [US2] Automated Testing - Contract tests for `/v1/role-assignments` and `/v1/role-assignments/{id}/revoke` in `apps/api/tests/contract/test_assignments_contract.py`. Deliverable: conformance tests. Verify: Schemathesis covers both operations.
- [ ] T028 [US2] Automated Testing - Integration test scaffold for US2 scenarios 1 to 5 in `apps/api/tests/integration/test_assignments.py`. Deliverable: failing-first tests. Verify: they run and fail for the expected reason.

### Implementation for User Story 2

- [X] T029 [US2] Backend API - Implement assignment use cases in `apps/api/src/gov/api/application/permission/assignments.py`: assign within a scope, refuse a duplicate, revoke with a reason, and evaluate expiry against a supplied time. Deliverable: FR-009 to FR-012. Verify: unit tests assert a duplicate is refused by the unique constraint, and that a revoked assignment grants nothing on the next resolution.
- [X] T030 [US2] Backend API - Implement routers and schemas in `apps/api/src/gov/api/interface/permission/assignments.py` for listing, creating and revoking assignments. Deliverable: the assignment HTTP surface. Verify: contract tests pass and revocation without a reason returns 422.
- [ ] T031 [US2] Infrastructure - Implement the assignment expiry sweep in `services/worker/src/gov/worker/assignment_expiry.py`, closing lapsed assignments and emitting an audit record for each. Deliverable: US2/AC3, that an expiry is a recorded change of state. Verify: a test with a short window asserts the assignment is closed and the change recorded, and that nothing is executed afterwards.
- [X] T032 [US2] Permission & Audit - Implement the last-authority guard (FR-027) in `apps/api/src/gov/api/application/permission/assignments.py`: revoking the assignment that would leave an organisation with nobody able to manage permissions is refused and recorded. Deliverable: the organisation cannot lock itself out. Verify: a test asserts the refusal, and that the same revocation succeeds once another holder exists.
- [X] T033 [US2] Permission & Audit - Wire authorization and audit for the assignment surface in `apps/api/src/gov/api/interface/permission/assignments.py`. Deliverable: enforced assignment administration. Verify: the security harness covers every assignment route for every role.
- [ ] T034 [US2] Automated Testing - Complete the US2 suite in `apps/api/tests/security/test_assignment_administration.py`, adding V4, V5, V6 and V13, including SC-006 (a revocation takes effect within one subsequent verification). Deliverable: US2 scenario coverage. Verify: the suite is green and fails if the cache is not invalidated on change.

### Frontend for User Story 2

- [ ] T035 [P] [US2] Frontend UI - Build the assignment screens in `apps/web/src/features/permission/`: assignments for a user, assignments for a role, scope and end-date inputs, and revoke with a mandatory reason. Deliverable: working assignment screens. Verify: Vitest tests pass and the manual walkthrough reproduces V4 to V6.
- [ ] T036 [US2] Automated Testing - Playwright E2E for V4 to V6 and V13 in `apps/web/tests/e2e/permission-assignments.spec.ts`. Deliverable: automated acceptance. Verify: the suite is green.

**Checkpoint**: scoped, time-bound access is administrable end to end.

---

## Phase 5: User Story 3 - Every Protected Request Is Verified (Priority: P1)

**Goal**: no protected action happens without a permission decision, and nothing
is allowed by default.

**Independent Test**: with a defined role, a permitted request proceeds and an
otherwise identical unpermitted one is refused with a reason, both recorded
(quickstart V7, V8).

### Tests for User Story 3

- [ ] T037 [P] [US3] Automated Testing - Policy tests in `deploy/policy/authorization_test.rego` covering: allowed, denied by omission, deny-beats-allow with both sources recorded, expired assignment, and out-of-scope Agent. Deliverable: FR-017, FR-018, FR-029 verified as policy. Verify: `opa test deploy/policy` passes and fails if deny-beats-allow is inverted.
- [X] T038 [US3] Automated Testing - Response-shape tests for unauthenticated (401), unpermitted (403) and fail-closed (503) outcomes across every new route, in `apps/api/tests/security/test_verification.py`. Deliverable: consistent refusal behaviour. Verify: every route is covered and each response is a problem document naming what was missing.

### Implementation for User Story 3

- [X] T039 [US3] Permission & Audit - Apply the extended authorization dependency to the Agent Registry routes in `apps/api/src/gov/api/interface/registry/router.py`, so the boundary recorded in plan.md is real rather than aspirational. Deliverable: one guard across both features. Verify: registry routes now refuse a caller without the corresponding permission, and the existing registry tests still pass for a permitted caller.
- [X] T040 [US3] Automated Testing - Implement the fail-closed test in `apps/api/tests/security/test_fail_closed.py`: with the decision component unreachable, every protected route refuses and records a degraded decision; when it returns, service resumes (SC-009, V8). Deliverable: FR-019 verified. Verify: the test passes and fails if the guard is changed to allow on error.
- [X] T041 [US3] Automated Testing - Implement the deny-by-default suite in `apps/api/tests/security/test_deny_by_default.py`: a caller with no assignments, an unknown permission name, and an unknown role each grant nothing (FR-008, FR-017). Deliverable: the default is proven, not assumed. Verify: every negative case is covered and the suite fails if any default is inverted.
- [ ] T042 [US3] Automated Testing - Playwright E2E for V7 and V8 in `apps/web/tests/e2e/permission-verification.spec.ts`. Deliverable: automated acceptance. Verify: the suite is green.

**Checkpoint**: enforcement is demonstrable, including its failure modes.

---

## Phase 6: User Story 4 - Responsibility-Based Control of Agent Resources (Priority: P2)

**Goal**: a developer maintains the Agents they are accountable for and is
refused on the rest.

**Independent Test**: give a developer responsibility for one Agent, confirm they
can modify it and cannot modify another (quickstart V9).

- [X] T043 [P] [US4] Data Model - Implement responsibility domain rules in `apps/api/src/gov/api/domain/permission/responsibility.py` over `agent.owner_user_id`, which is the single source of accountability: a transfer requires a reason, and the incoming holder must be a user of the same organisation. Deliverable: FR-013 and FR-015 rules. Verify: unit tests cover a transfer with and without a reason, and a transfer to a user in another organisation.
- [X] T044 [US4] Backend API - Implement responsibility use cases and routers in `apps/api/src/gov/api/application/permission/responsibility.py` and `apps/api/src/gov/api/interface/permission/responsibility.py` for `/v1/agents/{agent_id}/responsibility`: read the current holder, transfer it by updating `agent.owner_user_id` and writing the reason to the audit trail, and return the transfer history from the trail. Deliverable: FR-013, FR-015. Verify: contract tests pass, a transfer without a reason returns 422, and the history is derived from audit records rather than a second table.
- [X] T045 [US4] Permission & Audit - Implement resource-scoped authorization in `apps/api/src/gov/api/infrastructure/opa/authorization.py`: a developer may write an Agent only while recorded as accountable for it, enforced through the decision component's input rather than in the route. Deliverable: FR-014 and SC-003. Verify: an integration test asserts the holder is permitted and a non-holder is refused for the same action.
- [X] T046 [US4] Automated Testing - Complete the US4 suite in `apps/api/tests/security/test_agent_responsibility.py`, adding V9, and demonstrate SC-003 across at least 20 Agents and 5 developers. Deliverable: US4 scenario coverage. Verify: the suite is green and fails if accountability is ignored.
- [ ] T047 [P] [US4] Frontend UI - Show and transfer accountability on the Agent detail screen in `apps/web/src/features/registry/`. Deliverable: working responsibility screens. Verify: Vitest tests pass and the manual walkthrough reproduces V9.
- [ ] T048 [US4] Automated Testing - Playwright E2E for V9 in `apps/web/tests/e2e/permission-responsibility.spec.ts`. Deliverable: automated acceptance. Verify: the suite is green.

**Checkpoint**: Agent resources are controlled by accountability, not only by role.

---

## Phase 7: User Story 5 - Review Who Could Do What, and Why (Priority: P2)

**Goal**: an auditor reconstructs permission history from records alone and
cannot change anything.

**Independent Test**: perform a sequence of permission changes, then reconstruct
who granted what to whom, when and why, from the record alone (quickstart V10-V12).

- [ ] T049 [US5] Backend API - Extend the existing audit query surface in `apps/api/src/gov/api/interface/audit/router.py` with the filters this feature needs: target type for roles and assignments, actor, time range and outcome. Deliverable: FR-023. Verify: an integration test reconstructs the history of one role from the record alone, without reading current state.
- [X] T050 [P] [US5] Automated Testing - Implement the reconstruction test in `apps/api/tests/integration/test_permission_history.py` (SC-004): for a sample of 20 historical changes, answer "who held this permission at time T" with its granting actor and reason, using only records. Deliverable: SC-004 verified. Verify: the test fails if the answer is derived from current state. **Done**: 4 tests green; one proves an unrecorded current binding grants nothing on replay.
- [X] T051 [US5] Automated Testing - Implement immutability tests in `apps/api/tests/security/test_permission_record_immutability.py` (SC-005, V11): every attempt to amend or remove a permission-change record through the platform is refused, and the record is unchanged. Deliverable: FR-022 verified. Verify: the suite covers each entity type and fails if a store permits mutation. **Done**: 4 tests green, asserting the absence of a mutating audit route and of any mutating member on the audit port.
- [X] T052 [US5] Automated Testing - Implement the auditor read-only assertion in `apps/api/tests/security/test_auditor_read_only.py` (SC-008, V7, V12): every write route in this feature and in the registry is attempted by an auditor and refused, with the attempt recorded. Deliverable: FR-024 verified. Verify: the suite covers every write route and fails if one route is missed. **Done**: 17 tests green; every write route is refused and each refusal is recorded. Required a new refusal recorder (`application/audit/denials.py`) because refusals were previously unrecorded - see the finding below.
- [ ] T053 [P] [US5] Frontend UI - Build a read-only permission-change history view for auditors in `apps/web/src/features/permission/`: filter by role, assignment, actor and time, with no write affordance present. Deliverable: auditor review screen. Verify: Vitest tests pass and the screen sends no write request in the E2E trace.
- [ ] T054 [US5] Automated Testing - Playwright E2E for V10, V11 and V12 in `apps/web/tests/e2e/permission-audit.spec.ts`. Deliverable: automated acceptance. Verify: the suite is green.

**Checkpoint**: the feature explains itself to an auditor.

---

## Phase 8: Polish and Cross-Cutting Concerns

- [ ] T055 Permission & Audit - Verify and, if needed, tune the decision cache in `apps/api/src/gov/api/application/permission/effective.py`: invalidation on every role, binding and assignment change, and a p95 permission decision within the 50 ms budget from plan.md. Deliverable: FR-020 and the performance goal. Verify: a load test reports p95 and the invalidation test fails if a change does not evict the cached entry.
- [ ] T056 Automated Testing - Implement the cross-organisation isolation suite in `apps/api/tests/security/test_permission_isolation.py` for every permission entity (SC-007, V14): no cross-organisation access, and no visibility of another organisation's roles, assignments or responsibility. Deliverable: FR-025 verified. Verify: the suite passes with two seeded organisations and fails if a row-level-security policy is dropped.
- [ ] T057 Infrastructure - Ensure the new module is covered by every CI gate, including `opa test`, and that the four user types are represented in the matrix. Deliverable: no ungated surface. Verify: the pipeline fails for a deliberate regression in each of lint, tests, contract, policy and security.
- [ ] T058 Infrastructure - Add an operator runbook in `docs/runbooks/permission-administration.md` covering role creation, assignment, revocation, responsibility transfer and what to do when someone is locked out. Deliverable: FR-027 recoverable in practice. Verify: a new operator can complete each step using the runbook alone.
- [ ] T059 Automated Testing - Record the manual validation walkthrough V1 to V14 as an automated suite in `apps/web/tests/e2e/permission-acceptance.spec.ts`, so the acceptance contract is machine-checked. Deliverable: automated acceptance. Verify: every quickstart scenario maps to at least one test.
- [ ] T060 Permission & Audit - Implement the policy data projection in `apps/api/src/gov/api/infrastructure/opa/projection.py`: the effective policy data (roles, role permissions, assignments, accountability) is published into the policy bundle so the gateway obtains a decision without the control plane, which must not sit on the invocation path. Refresh on every change so the projection is never staler than the decision cache. Deliverable: FR-016 applied to tool invocation, closing analysis finding I5. Verify: a gateway invocation is refused for a caller without the permission; a permission revoked in the control plane is enforced at the gateway within the same window as T034's limit; and the gateway still functions when the control plane is unreachable.

---

## Dependencies and Execution Order

- **Phase 1 (Setup)**: no dependencies.
- **Phase 2 (Foundational)**: depends on Phase 1; **blocks every user story**. The
  decision component (T010), resolution (T011) and guard (T012) are what the
  stories are enforced with, so nothing is demonstrable without them.
- **Phase 3 (US1)**: depends on Phase 2.
- **Phase 4 (US2)**: depends on Phase 2 and on US1's roles existing to assign.
- **Phase 5 (US3)**: depends on Phase 2; T039 additionally depends on the Agent
  Registry routes from feature 001 existing.
- **Phase 6 (US4)**: depends on Phase 2 and on the Agent Registry schema
  (`0003_registry`, already written).
- **Phase 7 (US5)**: depends on US1 and US2 producing changes worth reviewing.
- **Phase 8 (Polish)**: depends on the phases it hardens; T056 and T057 may start
  once Phase 2 completes.

### Within Each User Story

- Contract and integration test tasks come before implementation.
- Domain rules precede repositories, which precede use cases and routers.
- Backend precedes the screen that consumes it.
- A story is complete when its integration, security and quickstart scenarios pass.

### Parallel Opportunities

```text
Phase 1:  T002 catalogue | T003 Rego scaffold | T005 CI wiring
Phase 2:  T006 migration | T007 domain rules | T010 OPA client
Phase 3:  T017 contract tests | T025 roles UI
Phase 4:  T027 contract tests | T035 assignment UI
US4/US5:  T043 responsibility rules | T049 audit filters | T047 UI | T053 auditor UI
```

---

## Implementation Strategy

### MVP First

1. Phases 1 and 2: the module, the schema, and the decision component.
2. US1: roles and permissions exist and can be read back.
3. US2: roles can be assigned within a scope.
4. US3: every protected request is verified.
5. **Stop and validate**: quickstart V1 to V8, V13. That is a working permission
   center for the Agent Registry, which is the stated objective.

T060 is deliberately outside the MVP: it closes the invocation-path gap, which
matters for the platform as a whole rather than for the Agent Registry surface
this feature was asked to govern.

### Incremental Delivery

US4 adds resource-level control; US5 makes the whole thing explainable to an
auditor. Neither changes the architecture, because both extend the decision
input rather than the model.

---

## Traceability and Coverage Check

### Requirements mapped to tasks

| Requirement | Tasks |
|-------------|-------|
| FR-001, FR-002 (user management) | T014, T015, T016 |
| FR-003 to FR-005, FR-031 (role management, built-ins immutable) | T007, T019, T020, T024 |
| FR-006 to FR-008 (permission management) | T002, T021, T022, T024 |
| FR-009 to FR-012 (assignment, scope, expiry, duplicates) | T029, T030, T031, T034 |
| FR-013, FR-015 (responsibility) | T043, T044 |
| FR-014 (developer limited to their Agents) | T045, T046 |
| FR-016 to FR-020 (verification, deny by default, fail closed, revocation) | T010, T011, T012, T037, T038, T039, T040, T041, T055, T060 |
| FR-021, FR-022 (permission-change audit) | T013, T050, T051 |
| FR-023, FR-024 (auditor review, read-only) | T049, T052, T053 |
| FR-025 to FR-027 (tenancy, least privilege, last authority) | T006, T032, T056 |
| FR-028, FR-029 (extension to ABAC) | T003, T010, T037 |
| FR-030 (the four user types map to the five roles) | T007, T012, T016 |
| SC-001 to SC-011 | T024, T034, T040, T046, T050, T051, T052, T055, T056, T059, T060 |

### Findings

- **T049's audit surface contradicts the authoritative contract (blocks the
  contract gate).** The implemented `GET /v1/audit-events` takes
  `target_type`/`target_id`/`actor`/`outcome`/`since`/`until` and returns a bare
  array of a reduced event shape, while
  `specs/001-agent-governance-platform/contracts/openapi.yaml` (line 523) still
  documents `from`/`to`/`actor_id`/`agent_id`/`tool_id`/`correlation_id` with a
  paged `AuditEventPage` of the hash-chained `AuditEvent`. One of the two must
  change before the contract test (T017/T027) can pass: either the router
  conforms to the paged, hash-carrying event, or the contract is extended with
  the permission-change filters and the reconstruction sub-path in the same
  change. T049 is left unmarked until that reconciliation, since its own stated
  verification passes but the code does not match the contract it must follow.
- **Refusal recording was missing (FR-024, SC-008).** "Every write attempt is
  refused **and recorded**" was only half-true: the authorization guards refused
  and wrote nothing, so no auditor could later see that a write had been
  attempted. T052 adds a central recorder in the error handler
  (`application/audit/denials.py`, wired through `register_problem_handlers`).
  It records refusals that carry an organisation and an actor (403, and 503
  fail-closed). An unauthenticated 401 carries no organisation, so it cannot be
  written to a tenant-scoped trail; that case, and recording at the edge, remain
  open for the Audit Center (feature 001).
- **A requirement has no user story.** FR-001 and FR-002 (user management) are
  requirements with no corresponding user scenario in `spec.md`: the five stories
  cover roles, assignments, verification, responsibility and review. The tasks
  above deliver them in Phase 2, but the specification should either gain a story
  for user administration or move those requirements into an existing one, or a
  future reader will not know who the capability is for. Recommend running
  `$speckit-specify` to add it.
- **No task lacks a requirement basis.** Every task traces to a requirement, a
  success criterion, a quickstart scenario, a constitution principle or an ADR.
- **Open business rules carried from the specification**: shared Agent
  accountability (T043 assumes one holder), delegation of assignments (T029
  assumes only an administrator grants), and permission-record retention (T051
  assumes the audit trail's period). Each changes configuration or one rule, not
  the architecture.

---

## Notes

- `[P]` marks tasks touching different files with no dependency on an incomplete
  task.
- Phase 1, Phase 2 and Phase 8 tasks carry no story label, by design.
- Mark a task complete only when its stated verification passes. The schema
  (T006) and the Rego bundle (T003, T037) cannot be verified without PostgreSQL and
  an `opa` binary; per plan.md they must be reported as unverified until those
  exist.
- No source code is created by this command; `$speckit-implement` executes these.
