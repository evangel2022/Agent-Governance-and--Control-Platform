# Quickstart and Validation Guide

**Feature**: `001-agent-governance-platform`
**Purpose**: start the development environment and prove the P1 governance loop
works end to end. This guide describes how to validate, not how to build.

## Prerequisites

- Docker Engine 26+ with Compose v2
- 8 GB RAM and 4 CPUs available to Docker (the full stack runs five backing
  services plus five application processes)
- `make` available in the shell, or the ability to run the underlying commands
- Ports 5432, 6379, 8181, 8200, 8080, 8000, 9000 and 5173 free

## Start the Development Stack

```bash
cp deploy/compose/.env.example deploy/compose/.env
docker compose -f deploy/compose/compose.yml up -d
```

This starts PostgreSQL, Redis, OPA, Vault (dev mode), Keycloak, the control-plane
API, the MCP gateway, the runner, the worker and the web SPA. Secrets are read
from Vault by the application processes; the `.env` file contains only
non-secret configuration (hosts, ports, log level).

Apply migrations and seed the built-in roles and an initial administrator:

```bash
make db-upgrade        # alembic upgrade head
make seed              # built-in roles, demo organisation, admin user
```

Confirm the stack is healthy:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:9000/healthz     # gateway
docker compose -f deploy/compose/compose.yml ps
```

Expected: the health endpoints return success and every service reports
`running` or `healthy`. If Vault is unreachable the API reports unhealthy rather
than starting with degraded secret handling.

Open the SPA at `http://localhost:5173` and sign in through the seeded Keycloak
realm. The seeded accounts cover each of the five roles so that the permission
matrix can be exercised manually.

## Access Points

| Service | URL |
|---------|-----|
| Web SPA | http://localhost:5173 |
| Control-plane API | http://localhost:8000 |
| OpenAPI document | http://localhost:8000/docs |
| MCP gateway | http://localhost:9000 |
| OPA | http://localhost:8181 |
| Keycloak | http://localhost:8080 |
| Vault (dev) | http://localhost:8200 |

## Validation Scenarios

Each scenario maps to acceptance criteria in [spec.md](./spec.md). They are
written to be run manually against the development stack and are mirrored by
automated tests in `apps/api/tests` and `apps/web/tests/e2e`.

### V1 - Registry rejects incomplete and duplicate entries (US1 scenario 4, FR-009)

1. Sign in as a Platform Administrator.
2. Create an Agent with a name but no owner.
3. Create a Tool without a risk level.
4. Create an Agent, then create it again with the same name.

Expected: steps 2 and 3 return a validation error naming the missing field and
create nothing; step 4 returns a conflict naming the existing identifier.
Reloading the registry shows no partial rows.

### V2 - One active version per Agent (US1 scenario 2, FR-006)

1. Add version `1.0.0` to the Agent and mark it released.
2. Add version `1.1.0` and mark it released.

Expected: `1.1.0` becomes the single released version and `1.0.0` is shown as
deprecated, not deleted.

### V3 - Policy allows one invocation and denies another (US2 scenarios 1-2)

1. As Security and Compliance, publish an `allow` policy for Agent A to Tool T.
2. Issue an invocation for Agent A to Tool T through the gateway.
3. Issue an invocation for Agent A to Tool U, which no policy grants.

Expected: step 2 succeeds and its audit record names the matched policy version;
step 3 is denied with a reason stating that no policy grants access. Both
attempts appear in the audit trail.

### V4 - Deny wins over allow (US2 scenario 3, FR-013)

1. Publish a broad `allow` policy and a narrower `deny` policy that both match
   the same Agent/Tool pair.
2. Issue the invocation.

Expected: the invocation is denied and the audit record lists both matched
policies with the conflict resolution stated.

### V5 - High-risk invocation cannot execute without approval (US3 scenarios 1-3, FR-016)

1. Classify Tool H as `high` risk.
2. Issue an invocation for Tool H.
3. Confirm the invocation is held and an approval request exists.
4. As a Business Approver, reject the request.
5. Re-issue the invocation, then approve it.

Expected: step 3 executes nothing. Step 4 leaves the invocation rejected with
the reason recorded. Step 5 executes only after the approval exists, and the
approval records the approver's identity, time and reason.

### V6 - Self-approval is refused (FR-004, FR-022 default)

1. As a user who is both the requester and a Business Approver, attempt to
   approve their own high-risk request.

Expected: the attempt is refused and the refusal is recorded. If dual control or
self-approval is later enabled by policy, this scenario is updated rather than
deleted.

### V7 - Approval expiry (US3 scenario 4, FR-020)

1. Set a short approval window, raise a high-risk request, and wait past expiry.

Expected: the request is recorded as `expired`, cannot be approved afterwards,
and the invocation never executes.

### V8 - Duplicate request does not duplicate execution (FR-022, edge case)

1. Issue an invocation with idempotency key `K`.
2. Issue the same invocation again with key `K`, including while it is pending
   approval.

Expected: the second call returns the original outcome; no second approval
request is created and no second execution occurs.

### V9 - Fail closed when policy is unavailable (FR-038, edge case)

1. Stop the OPA service.
2. Issue an invocation.
3. Restart OPA.

Expected: the invocation is denied while OPA is down, and the audit record marks
it as a degraded-mode denial with a reason. No invocation is allowed by default.

### V10 - Audit reconstruction (US2 scenario 4, FR-026, SC-003)

1. As an Auditor, filter the audit trail to the correlation id of one governed
   operation.

Expected: actor, tool, policy judgement, approval decision and final outcome are
all visible in one result set, and the chain is sufficient to explain the
outcome without consulting the application logs.

### V11 - Organisation isolation (FR-036, SC-010)

1. With two organisations seeded, authenticate as a user in organisation A and
   request an entity owned by organisation B by its identifier.

Expected: the response is a not-found rather than a permission error that
reveals existence, and no organisation B data appears anywhere in the response.
A direct database query without the organisation setting returns no rows.

## Verification and Test Commands

```bash
make lint            # ruff + mypy + eslint + tsc --noEmit
make test            # unit + integration (testcontainers)
make test-contract   # schemathesis against the running API
make test-security   # permission matrix, deny-by-default, fail-closed
make test-e2e        # playwright
make audit-verify    # recompute the audit hash chain
```

Expected: every command exits zero on a clean checkout, and `make audit-verify`
reports a valid chain for each organisation.

## Teardown

```bash
docker compose -f deploy/compose/compose.yml down
docker compose -f deploy/compose/compose.yml down -v   # also removes volumes
```
