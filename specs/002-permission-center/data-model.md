# Data Model: Permission Center

**Feature**: `002-permission-center`
**Date**: 2026-10-14
**Storage**: PostgreSQL 16, forward-only migrations

## Conventions

These follow the platform standard: UUIDv7 primary keys, `organisation_id`
`NOT NULL` on every tenant-scoped table, row-level security bound to
`app.organisation_id` and forced, `created_at`/`updated_at` in UTC, and no
`DELETE` grant to the application role for anything an audit record points at.

## What already exists, and is reused

This feature adds three tables. It deliberately does **not** create a parallel
identity model:

| Table | Created by | Reused for |
|-------|-----------|------------|
| `organisation` | `0001_identity` | The tenancy root |
| `user` | `0001_identity` | The people roles are assigned to |
| `role` | `0001_identity` | Both the five built-in roles and organisation-specific roles |
| `role_assignment` | `0001_identity` | Scoped, time-bound grants, with `scope_type`/`scope_id` and `expires_at` |
| `audit_event` | `0002_audit_event` | Permission-change records, via `target_type`/`target_id` |
| `agent` | `0003_registry` | The resource responsibility is recorded against |

### Columns the reused tables must gain

`role` and `role_assignment` exist, but neither carries everything this feature
needs. Revision `0005_permission_center` therefore **alters** them as well as
adding the new tables:

| Table | Added | Why |
|-------|-------|-----|
| `role` | `status` enum `active`/`retired`, default `active`, plus a check that a built-in role (`organisation_id IS NULL`) can never be retired | FR-005 retirement, FR-031 immutability |
| `role_assignment` | `revoked_at` timestamptz null, `revocation_reason` text null, with a check that a reason is present whenever `revoked_at` is set | FR-009 revocation with a recorded reason |

The role's stated purpose is the existing `role.description` column; the API
exposes that same column as `description` rather than inventing a second field.
Built-in status is derived from `organisation_id IS NULL`, so no `is_builtin`
column is added.

## New Revision: `0005_permission_center`

### permission

The catalogue of authorisable actions. Platform-wide reference data, not
per-organisation data, so it carries no `organisation_id` and no row-level
security: every deployment must recognise the same action names.

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| name | text | required, unique; stable identifier, e.g. `registry.agent.write` |
| resource | text | required; the family the action belongs to, e.g. `agent` |
| action | text | required; the verb, e.g. `read`, `write`, `retire` |
| description | text | required; plain description of what it authorises (FR-007) |
| is_builtin | boolean | required, default false; true for the permissions the platform's own roles depend on |
| created_at | timestamptz | required |

### role_permission

Binds a permission to a role. This is what makes a role grant something (FR-004,
FR-006).

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK to organisation, required |
| role_id | uuid | FK to role, required |
| permission_id | uuid | FK to permission, required |
| granted_by | uuid | FK to user, required |
| granted_at | timestamptz | required |
| rationale | text | nullable; why the binding exists |

Constraint: unique on (`role_id`, `permission_id`). Composite foreign key
(`organisation_id`, `role_id`) to `role(organisation_id, id)`, and (`organisation_id`,
`permission_id`) is not composite because `permission` is platform-wide.

### Responsibility reuses `agent.owner_user_id`

No new table. The Agent Registry already records the accountable person as
`agent.owner_user_id NOT NULL`, and that column is authoritative: a second table
naming the same person would be a second answer to "who is accountable", which is
how the two drift.

A transfer is an update to `owner_user_id` with its reason written to the audit
trail in the same transaction (ADR-0007). The trail is already the platform's
record of history, so the transfer is explainable without a bespoke history
table, and the "exactly one accountable person" invariant is enforced by the
column being `NOT NULL` rather than by a partial unique index.

## Indexes

| Index | Table | Definition | Why |
|-------|-------|------------|-----|
| `permission_name_uq` | permission | UNIQUE (`name`) | Stable lookup by name; prevents duplicate catalog entries |
| `permission_resource_idx` | permission | (`resource`, `action`) | Listing a resource family's actions for the administration screen |
| `role_permission_uq` | role_permission | UNIQUE (`role_id`, `permission_id`) | A permission is bound to a role once |
| `role_permission_role_idx` | role_permission | (`organisation_id`, `role_id`) | Resolving a role's effective permissions, on the request path |
| `role_permission_permission_idx` | role_permission | (`permission_id`) | "Which roles grant this permission", for review and for impact analysis |
| `agent_owner_idx` | agent | (`organisation_id`, `owner_user_id`) | Already exists in `0003_registry`; serves "which Agents is this person accountable for", the authorisation query |

The assignment lookups the decision path needs are already served by
`role_assignment_user_idx` and `role_assignment_expiry_idx` from `0001_identity`,
which is why no further index is added for them.

## Tenancy

- `role_permission` carries `organisation_id` with forced row-level security,
  keyed to `app.organisation_id` and failing closed when it is unset. `agent`
  already carries the same policy from `0003_registry`.
- `permission` is platform-wide reference data and is not tenant-filtered; it
  contains no organisation's information, only the names of actions.
- Composite foreign keys keep a child row inside its own organisation: a
  `role_permission` cannot bind a role from another tenant. `agent.owner_user_id`
  is already a composite key against `user(organisation_id, id)`.

## Audit Mapping

No new audit table. Every change writes an `audit_event` row in the same
transaction (ADR-0007):

| Change | `event_type` | `target_type` | `action` |
|--------|--------------|---------------|----------|
| Role created, amended, retired | `identity_change` | `role` | `create` / `update` / `retire` |
| Permission bound or unbound | `identity_change` | `role` | `bind_permission` / `unbind_permission` |
| Role assigned or revoked | `identity_change` | `role_assignment` | `assign` / `revoke` |
| Responsibility assigned or transferred | `identity_change` | `agent` | `assign_responsibility` / `transfer_responsibility`, with the transfer reason |
| Request refused for lack of permission | `policy_judgement` | the requested target | `authorize` |

The audit trail already carries the actor, target, outcome, reason and time that
FR-021 requires, and its hash chain makes the record permanent in the way FR-022
demands. The `audit_target_idx` index from `0002_audit_event` answers "every
change to this role or assignment" without a new index.

## State Transitions

**Role**: `active` → `retired`. A retired role grants nothing and cannot be
assigned; it is never deleted, because past decisions reference it (FR-005).

**Role assignment**: created → effective → (expired | revoked). An expired
assignment is one whose `expires_at` has passed; a revoked one has been closed
with a reason. Both stop granting at the next verification (FR-011, FR-020).

**Agent responsibility**: held by one person → transferred, by updating
`agent.owner_user_id` and recording the reason in the audit trail. An Agent
always has exactly one accountable person, because the column is `NOT NULL`
(FR-013).

## Validation Rules Derived from Requirements

- A role created without permissions grants nothing; it is not an error, it is
  the required starting state (FR-004).
- Binding an unknown permission name is refused rather than stored (FR-008).
- A duplicate assignment of the same role to the same user in the same scope is
  refused by the unique index, not only by the application (FR-012).
- The five built-in roles are inserted by migration with fixed identifiers, and
  the `role.status` check refuses to retire one (FR-031).
- An organisation cannot end up with no one able to manage permissions: the last
  such assignment cannot be revoked (FR-027).
