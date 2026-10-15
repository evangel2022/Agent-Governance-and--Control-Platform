# Data Model: Agent Governance and Control Platform

**Feature**: `001-agent-governance-platform`
**Date**: 2026-10-13
**Storage**: PostgreSQL 16, forward-only migrations via Alembic

## Conventions

- **Identity**: every table has a UUIDv7 primary key `id` (time-ordered, which
  keeps index locality good on append-heavy audit and invocation tables).
- **Tenancy**: every tenant-scoped table has `organisation_id UUID NOT NULL`
  referencing `organisation(id)`, and carries a row-level-security policy bound
  to `current_setting('app.organisation_id')`. The `organisation` table itself
  is the tenancy root and is not itself tenant-filtered.
- **Timestamps**: `created_at`, `updated_at` are `timestamptz` in UTC. Audit and
  invocation tables additionally carry the business-time `occurred_at`.
- **Immutability**: `audit_event` and `approval_decision` are append-only. The
  application role has no `UPDATE` or `DELETE` grant on them; corrections are
  new rows that reference the row they supersede.
- **Soft retirement**: registry entities are retired with a status transition
  rather than deletion, because audit records reference them.
- **Enumerations**: implemented as PostgreSQL enums or constrained text with a
  check constraint; the migration is the authority on allowed values.
- **JSONB**: used only for genuinely open shapes (`audit_event.detail`,
  `policy_version.document_metadata`, `evaluation_report.results`) and always
  with an explicit schema version inside the document.

## Entity Overview

```text
organisation ─┬─< user ──< role_assignment >── role
              │
              ├─< agent ──< agent_version >── model_usage_restriction >── model
              │        │
              │        └─< agent_tool_grant >── tool ──< tool_permission
              │
              ├─< policy ──< policy_version
              │
              ├─< invocation ─┬─< policy_judgement
              │               ├── approval_request ──< approval_decision
              │               └── audit_event (by correlation)
              │
              ├─< approval_request ──< approval_decision
              │
              ├─< test_dataset ──< evaluation_task ──< evaluation_report
              │
              ├─< release ──< release_event
              │
              ├─< risk_event
              │
              └─< outbox_event

audit_event ──< audit_export
audit_event ──< risk_event
```

## Entities

### organisation

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| name | text | required, unique per deployment unless multi-organisation is enabled |
| status | enum | `active`, `suspended`, `closed` |
| residency_region | text | nullable; used when residency rules apply |
| created_at / updated_at | timestamptz | required |

### user

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| external_subject | text | OIDC subject; unique with `organisation_id` |
| display_name, email | text | required, email format validated |
| status | enum | `active`, `disabled` |
| last_seen_at | timestamptz | nullable |

### role

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | nullable for the five built-in roles |
| code | enum | `platform_administrator`, `agent_developer`, `security_compliance`, `business_approver`, `auditor` |
| name, description | text | required |

Built-in roles are seeded by migration. `business_approver` carries the distinct
`approval.decide` permission; it is not implied by administrator status (FR-001,
FR-004).

### role_assignment

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| user_id | uuid | FK, required |
| role_id | uuid | FK, required |
| scope_type | enum | `organisation`, `agent`, `tool` |
| scope_id | uuid | nullable; required when scope_type is not `organisation` |
| granted_by, granted_at | uuid / timestamptz | required |
| expires_at | timestamptz | nullable; supports time-bound grants (least privilege) |

Constraint: unique on (`organisation_id`, `user_id`, `role_id`, `scope_type`,
`scope_id`). Whether a user may hold several roles at once is **OPEN**
(open business rule 13); the model supports it, and the permission union is
computed at authorization time.

### agent

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| name | text | required; unique per organisation (`agent_organisation_name_uq`) |
| description | text | nullable |
| owner_user_id | uuid | FK, required (accountability) |
| status | enum | `draft`, `active`, `deprecated`, `retired` |
| created_at / updated_at | timestamptz | required |

### agent_version

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| agent_id | uuid | FK, required |
| version | text | required; semantic-version-shaped; unique per agent |
| owner_user_id | uuid | FK, required |
| status | enum | `draft`, `in_review`, `released`, `deprecated`, `retired` |
| model_id | uuid | FK to model, nullable |
| released_at | timestamptz | nullable |
| created_at / updated_at | timestamptz | required |

Constraint: at most one `released` version per agent, enforced by a partial
unique index `agent_version_active_uq ON agent_version (agent_id) WHERE status =
'released'` (FR-006).

**Derived, not stored.** Two values are deliberately absent from the schema
because both are cheap to compute and expensive to keep correct:

- `agent.active_version_id` is the version where `status = 'released'`. The
  partial unique index above guarantees at most one, so the lookup is a single
  index probe. The API contract exposes the field; the entity does not store it.
- `agent_version.derived_risk_level` is the highest risk level among the tools
  the version may invoke. That association (`agent_tool_grant`) arrives with the
  Policy Center, so a stored copy would need maintaining from a table that does
  not exist yet.

### tool

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| name | text | required; unique per organisation |
| description | text | nullable |
| risk_level | enum | `low`, `medium`, `high`, `critical` (FR-007) |
| risk_basis | text | how the level was determined; required |
| adapter_ref | text | identifier of the tool adapter the gateway dispatches to |
| status | enum | `draft`, `active`, `deprecated`, `retired` |
| created_at / updated_at | timestamptz | required |

**Derived, not stored.** `requires_sandbox_class` (`shared` for low and medium
risk, `dedicated` for high and critical, per ADR-0006) is a pure function of
`risk_level`. Persisting it would create a second copy of a decision that can
only be wrong, so it is computed at read time.

### tool_permission

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| tool_id | uuid | FK, required |
| resource_type | text | e.g. `erp.invoice`, `scm.purchase_order` |
| action | enum | `read`, `write`, `execute`, `approve`, `delete` |
| data_class | enum | `public`, `internal`, `confidential`, `restricted` (taxonomy fixed by FR-043) |
| narrowing | jsonb | optional narrowing (row filters, limits); defaults to `{}` |

Constraint: unique on (`tool_id`, `resource_type`, `action`, `data_class`).

Naming note: this column is called `narrowing` rather than `constraint` because
`CONSTRAINT` is a reserved word in PostgreSQL and would require quoting at every
use.

### model

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| name | text | required, unique per organisation |
| vendor | text | required (FR-008) |
| version | text | nullable |
| status | enum | `approved`, `restricted`, `withdrawn` |
| created_at / updated_at | timestamptz | required |

### model_usage_restriction

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| model_id | uuid | FK, required |
| restriction_type | enum | `allowed`, `prohibited` |
| dimension | enum | `scenario`, `data_class`, `region` |
| value | text | required; permitted/prohibited value for the dimension |
| reason | text | required for `prohibited` |

### policy

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| name | text | required, unique per organisation |
| effect | enum | `allow`, `deny` |
| agent_id | uuid | FK, nullable (null = any agent in scope) |
| tool_id | uuid | FK, nullable |
| environment | text | required; e.g. `prod`, `staging` |
| valid_from / valid_until | timestamptz | nullable window |
| priority | integer | required; deterministic conflict ordering |
| status | enum | `draft`, `published`, `retired` |
| current_version_id | uuid | FK to policy_version |
| created_by, created_at | uuid / timestamptz | required |

### policy_version

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| policy_id | uuid | FK, required |
| version_number | integer | monotonic per policy |
| rego_module | text | the Rego source at this version |
| bundle_digest | text | digest published to OPA; decisions cite this |
| document_metadata | jsonb | non-executable metadata |
| published_at | timestamptz | nullable until published |
| published_by | uuid | FK to user |

Constraint: unique on (`policy_id`, `version_number`). Published versions are
immutable; a change creates a new version (FR-015).

### agent_tool_grant

Resolved, effective permission between an agent version and a tool. This is a
derived read model maintained from policy versions so that the gateway's hot
path does not need to re-resolve every policy on every call.

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| agent_version_id | uuid | FK, required |
| tool_id | uuid | FK, required |
| effect | enum | `allow`, `deny` |
| policy_version_id | uuid | FK, the version this grant was derived from |
| derived_at | timestamptz | required |

Constraint: unique on (`agent_version_id`, `tool_id`, `policy_version_id`).

### invocation

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| agent_version_id | uuid | FK, required |
| tool_id | uuid | FK, required |
| idempotency_key | text | required; caller-supplied or derived |
| requested_by | uuid | FK to user or agent identity |
| parameters_digest | text | hash of the parameters; full parameters only if policy permits |
| risk_level | enum | snapshot at decision time |
| status | enum | `pending_policy`, `denied`, `pending_approval`, `approved`, `executing`, `succeeded`, `failed`, `expired`, `cancelled` |
| correlation_id | uuid | ties every event of one operation together |
| occurred_at | timestamptz | required |

Constraints: unique on (`organisation_id`, `idempotency_key`) — the mechanism
behind at-most-once execution (FR-022 and the duplicate-request edge case).

### policy_judgement

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| invocation_id | uuid | FK, required |
| decision | enum | `allow`, `deny` |
| matched_policy_version_ids | uuid[] | every matching policy, not only the winner (FR-013) |
| conflict_resolution | text | how the outcome was chosen (e.g. explicit deny wins) |
| applied_risk_level | enum | required |
| reason | text | required, human-readable (FR-014, FR-039) |
| degraded_mode | boolean | true when the decision was fail-closed due to an outage |
| decided_at | timestamptz | required |

### approval_request

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| invocation_id | uuid | FK, required, unique (one approval per invocation) |
| requested_by | uuid | FK, required |
| required_approvals | smallint | default 1; set to 2 for dual control (FR-022) |
| allow_self_approval | boolean | default false (FR-022) |
| status | enum | `pending`, `approved`, `rejected`, `expired`, `cancelled` |
| expires_at | timestamptz | required; no default — set from policy |
| evidence | jsonb | policy judgement, parameter digest, risk basis |
| created_at / updated_at | timestamptz | required |

### approval_decision

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| approval_request_id | uuid | FK, required |
| approver_user_id | uuid | FK, required |
| decision | enum | `approve`, `reject` |
| reason | text | required |
| decided_at | timestamptz | required |

Append-only; no `UPDATE`/`DELETE` grants (FR-019). For dual control the request
closes only when the count of distinct approving users reaches
`required_approvals`.

### audit_event

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| sequence | bigint | per-organisation monotonic; unique with organisation |
| event_type | enum | `invocation`, `policy_judgement`, `approval`, `registry_change`, `release_change`, `identity_change`, `evaluation`, `system` |
| actor_type | enum | `user`, `agent`, `system` |
| actor_id | uuid | required |
| action | text | required |
| target_type / target_id | text / uuid | required |
| outcome | enum | `success`, `denied`, `failure`, `pending` |
| reason | text | nullable but required for any non-success outcome |
| detail | jsonb | schema-versioned payload |
| correlation_id | uuid | nullable |
| occurred_at | timestamptz | required (business time) |
| recorded_at | timestamptz | required (write time); the two differ under retry |
| prev_hash | text | hash of the previous entry in the chain, null for the first |
| entry_hash | text | hash over the canonical fields of this row |

### audit_export

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| requested_by | uuid | FK, required |
| filter | jsonb | the query that produced the export |
| status | enum | `queued`, `running`, `ready`, `failed`, `expired` |
| object_ref | text | storage location, nullable until ready |
| row_count | integer | nullable |
| expires_at | timestamptz | download link expiry |

### risk_event

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| severity | enum | `low`, `medium`, `high`, `critical` |
| summary | text | required |
| source | enum | `audit_chain_mismatch`, `rollback_failure`, `approval_anomaly`, `policy_degraded_mode`, `manual` |
| audit_event_id | uuid | FK to audit_event, nullable; the record the event points at |
| status | enum | `open`, `acknowledged`, `resolved` |
| detected_at | timestamptz | required |
| resolved_at | timestamptz | nullable |
| resolved_by | uuid | FK to user, nullable |

Risk events are raised by the platform itself (audit chain mismatch, failed
rollback, approval anomaly, a spike of fail-closed denials) and are surfaced on
the dashboard and as alerts. They are distinct from audit events: an audit event
records what happened, while a risk event records that something requires
attention. FR-033 requires them, so they are a first-class entity rather than a
derived view.

### test_dataset

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| name | text | required |
| version_number | integer | required; monotonic per name |
| object_ref | text | storage location of the immutable dataset |
| content_digest | text | required; detects post-hoc change |
| is_immutable | boolean | true once used by any evaluation task (FR-028) |
| created_at | timestamptz | required |

### evaluation_task

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| agent_version_id | uuid | FK, required |
| test_dataset_id | uuid | FK, required |
| criteria | jsonb | required; evaluation criteria definitions |
| status | enum | `queued`, `running`, `completed`, `failed`, `cancelled` |
| created_by, created_at | uuid / timestamptz | required |

### evaluation_report

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| evaluation_task_id | uuid | FK, required, unique |
| overall_result | enum | `pass`, `fail`, `inconclusive` |
| blocking_failure | boolean | true when a blocking criterion failed (FR-029) |
| results | jsonb | per-criterion observed vs expected |
| produced_at | timestamptz | required |

### release

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| agent_id | uuid | FK, required |
| agent_version_id | uuid | FK, required |
| state | enum | `released`, `canary`, `promoted`, `rolled_back`, `decommissioned` |
| canary_percent | smallint | nullable; required when state is `canary` |
| previous_release_id | uuid | nullable; set on rollback targets |
| created_by, created_at | uuid / timestamptz | required |

Constraint: at most one non-terminal release per agent
(`release_active_uq ON release (agent_id) WHERE state IN ('released','canary')`).

### release_event

Append-only record of each transition: `release_id`, `from_state`, `to_state`,
`actor_id`, `reason` (required for rollback, FR-031), `occurred_at`.

### outbox_event

| Field | Type | Rules |
|-------|------|-------|
| id | uuid | PK |
| organisation_id | uuid | FK, required |
| aggregate_type / aggregate_id | text / uuid | required |
| event_type | text | required |
| payload | jsonb | schema-versioned |
| created_at | timestamptz | required |
| published_at | timestamptz | nullable; null means not yet relayed |
| attempts | integer | default 0 |
| last_error | text | nullable |

## State Transitions

**Invocation** (the core governance state machine):

```text
pending_policy ──deny──────────────▶ denied
      │
      ├──allow, risk low/medium────▶ executing ──▶ succeeded | failed
      │
      └──allow, risk high/critical─▶ pending_approval
                                        │
        ┌───────────────────────────────┼──────────────────────────┐
        │ approved                      │ rejected                 │ expired
        ▼                               ▼                          ▼
     executing ──▶ succeeded|failed   rejected                   expired
```

Terminal states: `denied`, `succeeded`, `failed`, `rejected`, `expired`,
`cancelled`. A terminal invocation is never reopened; a retry is a new
invocation sharing the same idempotency key, which the unique constraint turns
into a replay of the original outcome rather than a new execution.

**ApprovalRequest**: `pending` → `approved` | `rejected` | `expired` |
`cancelled`. Transitions out of `pending` are one-way and are recorded as
`approval_decision` (append-only) plus a status update.

**AgentVersion**: `draft` → `in_review` → `released` → `deprecated` →
`retired`. Only `released` is invocable by default.

**Tool**: `draft` → `active` → `deprecated` → `retired`. Raising `risk_level`
on an `active` tool requires re-evaluation of in-flight approvals (edge case
"risk level raised while a request is pending").

**Policy**: `draft` → `published` → `retired`. `published` versions are
immutable.

**Release**: `released` → `canary` → `promoted`; `canary` or `promoted` →
`rolled_back`; any → `decommissioned`.

**EvaluationTask**: `queued` → `running` → `completed` | `failed` |
`cancelled`.

## Indexes and Constraints

Beyond primary keys, foreign keys and the uniqueness constraints listed above:

| Index | Table | Definition | Why |
|-------|-------|------------|-----|
| `invocation_org_time_idx` | invocation | (`organisation_id`, `occurred_at` DESC) | Operational and dashboard scans |
| `invocation_idempotency_uq` | invocation | UNIQUE (`organisation_id`, `idempotency_key`) | At-most-once execution |
| `invocation_pending_approval_idx` | invocation | (`organisation_id`, `status`) WHERE status = 'pending_approval' | Approval queue and dashboard |
| `audit_org_time_idx` | audit_event | (`organisation_id`, `occurred_at` DESC) | Primary audit query |
| `audit_org_seq_uq` | audit_event | UNIQUE (`organisation_id`, `sequence`) | Chain integrity anchor |
| `audit_actor_idx` | audit_event | (`organisation_id`, `actor_id`, `occurred_at` DESC) | Actor investigation |
| `audit_target_idx` | audit_event | (`organisation_id`, `target_type`, `target_id`, `occurred_at` DESC) | Reconstruct one operation (FR-026) |
| `audit_correlation_idx` | audit_event | (`organisation_id`, `correlation_id`) WHERE correlation_id IS NOT NULL | Follow one operation across events |
| `audit_detail_gin` | audit_event | GIN (`detail` jsonb_path_ops) | Filtered audit search without scans |
| `approval_pending_idx` | approval_request | (`organisation_id`, `status`, `expires_at`) | Pending queue and expiry sweep |
| `approval_invocation_uq` | approval_request | UNIQUE (`organisation_id`, `invocation_id`) | One approval per invocation |
| `policy_lookup_idx` | policy | (`organisation_id`, `agent_id`, `tool_id`, `environment`) | Decision-time lookup |
| `policy_version_uq` | policy_version | UNIQUE (`policy_id`, `version_number`) | Version integrity |
| `agent_org_name_uq` | agent | UNIQUE (`organisation_id`, `name`) | Duplicate rejection |
| `agent_version_uq` | agent_version | UNIQUE (`agent_id`, `version`) | Duplicate rejection |
| `agent_version_active_uq` | agent_version | UNIQUE (`agent_id`) WHERE status = 'released' | One active version |
| `tool_high_risk_idx` | tool | (`organisation_id`) WHERE risk_level IN ('high','critical') | High-risk inventory |
| `release_active_uq` | release | UNIQUE (`agent_id`) WHERE state IN ('released','canary') | One active release |
| `outbox_unpublished_idx` | outbox_event | (`created_at`) WHERE published_at IS NULL | Relay efficiency |
| `dataset_digest_uq` | test_dataset | UNIQUE (`organisation_id`, `name`, `version_number`) | Dataset version integrity |
| `risk_event_open_idx` | risk_event | (`organisation_id`, `status`, `detected_at` DESC) | Dashboard risk list and alerting |

## Validation Rules Derived from Requirements

- A registry write missing a required field (owner, risk level, tool permission
  set, model vendor) is rejected atomically; no partial row is created (FR-009,
  US1 scenario 4).
- An invocation for an `agent_version` that is not `released`, or a `tool` that
  is not `active`, is refused and recorded (edge case "unregistered Agent, Tool
  or model").
- A policy evaluation that matches nothing yields `decision = deny` with
  `reason` naming the absence of a grant (FR-012).
- An `invocation` with `risk_level` in (`high`, `critical`) cannot leave
  `pending_approval` without a linked `approval_request` in `approved` state
  (FR-016); this is enforced by a foreign-key-plus-check arrangement and a
  service-level invariant tested in the security suite.
- `approval_decision` rows may not be updated or deleted; a correction is a new
  row that references its predecessor (FR-019).
- A `test_dataset` with `is_immutable = true` cannot change `object_ref` or
  `content_digest`; a change creates a new version (FR-028).
- Every `audit_event` row has a non-null `entry_hash` and a `prev_hash` matching
  the previous row's `entry_hash` for that organisation, or null when it is the
  first (R6 / ADR-0007).
