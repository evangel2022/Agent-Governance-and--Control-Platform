# Quickstart and Validation Guide: Permission Center

**Feature**: `002-permission-center`
**Purpose**: exercise the Permission Center end to end and prove its acceptance
criteria. This guide describes how to validate, not how to build.

## Prerequisites

The platform development stack must be running (`make up` from repository root),
with an administrator, a developer, an auditor and two Agents already seeded.
See the platform quickstart for the stack itself.

## Validation Scenarios

Each scenario maps to acceptance criteria in [spec.md](./spec.md). They are
mirrored by automated tests; the manual walkthrough is what a reviewer runs.

### V1 - An administrator creates a role that grants nothing (US1/AC1, FR-004)

1. Sign in as Platform Administrator.
2. Create a role named `erp-invoice-owner` with a stated purpose.
3. Read the role back.

Expected: the role exists with an **empty** permission set. Creating a role
without permissions is the required starting state, not an omission.

### V2 - An administrator binds and unbinds permissions (US1/AC2-3, FR-006)

1. Bind `registry.agent.read`, `registry.agent.write` and `registry.agent.retire`
   to the role.
2. Read the role back, then unbind `registry.agent.retire`.

Expected: the effective set shows three permissions, then two. Both changes
appear in the permission-change record with the actor and the permission
involved.

### V3 - Duplicate and unknown names are refused (US1/AC4, FR-008)

1. Create a second role with the same name as an existing one.
2. Bind a permission whose name the catalogue does not contain.

Expected: the duplicate is refused and the existing role is unchanged; the
unknown permission is refused rather than stored.

### V4 - An administrator assigns within a scope (US2/AC1-2, FR-010)

1. Assign the role to the developer, scoped to Agent A only.
2. As the developer, modify Agent A.
3. As the developer, modify Agent B, for which they hold nothing.

Expected: step 2 succeeds; step 3 is refused with a reason naming what was
missing, and the refusal is recorded.

### V5 - Assignments expire and revoke (US2/AC3-4, FR-011, FR-020)

1. Create an assignment with a short end date, and a second one to revoke
   immediately.
2. Wait past the end date; revoke the second.
3. As the affected developer, retry a permitted action in each case.

Expected: both refusals happen at the **next verification**, with no successful
action observed after either, and both changes recorded with a reason.

### V6 - A duplicate assignment is refused (US2/AC5, FR-012)

1. Assign the same role to the same user in the same scope twice.

Expected: the second is refused; only one grant exists.

### V7 - An unpermitted request is rejected before any change (US3/AC1-3, FR-016-017)

1. As the auditor, attempt to create a role, bind a permission, and change an
   assignment.
2. As the auditor, attempt to modify an Agent.

Expected: every attempt is refused, nothing changes, and each refusal is
recorded with the caller, action, target, outcome and reason.

### V8 - Verification fails closed (US3, FR-019, SC-009)

1. Make the policy component unreachable.
2. Attempt a protected request.
3. Restore the component.

Expected: the request is refused while the component is down, and the refusal is
recorded as a degraded-mode decision with a reason. Nothing is allowed by
default.

### V9 - Responsibility transfer (US4/AC3-4, FR-013, FR-015)

1. Note the Agent's current accountable person.
2. Transfer responsibility to the developer, with a reason.
3. As the former holder, retry a modification; as the new holder, make one.

Expected: the former holder is refused, the new holder succeeds, and the transfer
appears in the record with its reason and the closing of the previous holder.

### V10 - An auditor reconstructs history (US5/AC1-2, FR-023, SC-004)

1. As auditor, list the permission changes affecting one role.
2. Ask who held a given permission at the time of a past action.

Expected: the answer is derived from recorded changes — actor, target, change,
time, reason — not from current state, and is obtainable without engineering
help.

### V11 - Permission-change records are permanent (US5/AC4, FR-022, SC-005)

1. Attempt to amend or delete a permission-change record.

Expected: refused in every case; the record is unchanged.

### V12 - Built-in roles are immutable (FR-031)

1. As administrator, attempt to rename, re-permission or retire each of the five
   built-in roles.

Expected: every attempt is refused, and the built-in matrix is unchanged.

### V13 - The last authority cannot be removed (FR-027)

1. As the only holder of authority to manage permissions, attempt to revoke your
   own last assignment.

Expected: refused, so the organisation cannot lock itself out, and the refusal is
recorded.

### V14 - Cross-organisation isolation (FR-025, SC-007)

1. With two organisations seeded, attempt to assign a role to a user of the other
   organisation, and to scope an assignment to the other organisation's Agent.

Expected: both are refused rather than merely hidden, and no permission data from
the other organisation is visible anywhere in the response.

## Verification and Test Commands

```bash
make test-security     # the four user types against every permission route
make test-contract     # new endpoints against the committed contract
make test              # unit and integration, including RLS isolation
opa test deploy/policy # RBAC decisions, including deny-beats-allow and expiry
cd apps/web && npm run test:e2e
```

## Known Verification Limits

In an environment without PostgreSQL, Docker or an `opa` binary, the following
cannot be run and must not be reported as verified:

- `alembic upgrade head` and the resulting RLS and composite-key behaviour
- `opa test` against `deploy/policy/authorization.rego`
- integration tests that use testcontainers
- the console end-to-end suites

Unit and use-case tests against in-memory ports do run, and are the evidence to
rely on until the environment is available.
