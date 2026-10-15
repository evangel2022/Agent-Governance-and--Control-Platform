# Domain Event Contract

**Feature**: `001-agent-governance-platform`
**Transport**: PostgreSQL transactional outbox → Redis Streams
**Delivery**: at-least-once, consumers must be idempotent on `event_id`

Domain events are used for projections, notifications and the dashboard. They
are **not** the audit record of truth: `audit_event` rows are written in the same
transaction as the state change they describe (ADR-0007). A lost or delayed
event therefore cannot create an audit gap.

## Envelope

Every event shares this envelope:

```json
{
  "event_id": "0198f2c1-6c2e-7a11-9b31-2f5a1c9e4b70",
  "event_type": "policy.judged",
  "schema_version": 1,
  "organisation_id": "6f1a1d2e-0f7a-4a6f-9a1e-2c74f0b1a3c9",
  "occurred_at": "2026-10-13T09:15:32.481Z",
  "recorded_at": "2026-10-13T09:15:32.512Z",
  "correlation_id": "b21c9e44-77aa-4c15-9d02-8f3e6c1a5d27",
  "actor": {
    "type": "user",
    "id": "3d9a5b10-8e42-4f77-b0c1-6a2e9d4f5b18"
  },
  "payload": {}
}
```

Rules:

- `event_id` is globally unique and is the idempotency key for consumers.
- `organisation_id` is mandatory on every event; a consumer without a matching
  organisation context must discard the event rather than process it unscoped.
- `schema_version` increments on any breaking payload change; additive changes
  do not increment it.
- `occurred_at` is business time; `recorded_at` is write time. They differ when
  a state change is retried, and both are preserved.
- Payloads never contain secrets, full credentials, or raw sensitive data.
  Where parameters are relevant they are carried as a digest, matching the
  audit rule.

## Event Catalog

| Event | Emitted when | Key payload fields | Consumers |
|-------|--------------|--------------------|-----------|
| `agent.registered` | An agent or version is created or updated | `agent_id`, `agent_version_id?`, `status`, `owner_user_id` | Dashboard projection, notification |
| `tool.registered` | A tool is created or its risk level or permissions change | `tool_id`, `risk_level`, `risk_basis`, `permission_count` | Policy cache invalidation, dashboard |
| `model.registered` | A model or its usage restrictions change | `model_id`, `vendor`, `status`, `restriction_count` | Registry projection |
| `policy.version_published` | A new policy version becomes effective | `policy_id`, `policy_version_id`, `bundle_digest`, `effective_from` | Grant projection rebuild, cache invalidation, audit |
| `invocation.requested` | The gateway admits an invocation for evaluation | `invocation_id`, `agent_version_id`, `tool_id`, `idempotency_key`, `risk_level` | Approval queue, dashboard |
| `policy.judged` | A policy decision is made | `invocation_id`, `decision`, `matched_policy_version_ids`, `reason`, `degraded_mode` | Audit projection, dashboard metrics |
| `approval.requested` | A high-risk invocation is held | `approval_request_id`, `invocation_id`, `required_approvals`, `expires_at` | Approver notification, dashboard |
| `approval.decided` | An approver approves or rejects | `approval_request_id`, `decision`, `approver_user_id`, `reason` | Gateway resume, dashboard |
| `approval.expired` | The expiry worker closes an undecided request | `approval_request_id`, `expired_at` | Gateway (deny), dashboard |
| `invocation.completed` | An invocation reaches a terminal state | `invocation_id`, `status`, `duration_ms` | Dashboard metrics |
| `release.state_changed` | Release, canary, promote, rollback or decommission | `release_id`, `agent_id`, `from_state`, `to_state`, `reason` | Registry projection, audit, notification |
| `evaluation.completed` | An evaluation task finishes | `evaluation_task_id`, `agent_version_id`, `overall_result`, `blocking_failure` | Release gate, dashboard |
| `audit.event_recorded` | An audit row was recorded. This is a notification only: the row itself is written in the same transaction as the change it describes (ADR-0007), never by an event consumer | `audit_event_id`, `sequence`, `event_type` | Audit export, SIEM forwarding (optional) |

## Representative Payloads

### `policy.judged`

```json
{
  "event_id": "0198f2c1-6c2e-7a22-9b31-2f5a1c9e4b71",
  "event_type": "policy.judged",
  "schema_version": 1,
  "organisation_id": "6f1a1d2e-0f7a-4a6f-9a1e-2c74f0b1a3c9",
  "occurred_at": "2026-10-13T09:15:32.481Z",
  "recorded_at": "2026-10-13T09:15:32.512Z",
  "correlation_id": "b21c9e44-77aa-4c15-9d02-8f3e6c1a5d27",
  "actor": { "type": "agent", "id": "9c1f0a7d-2b3e-4d18-8f52-0e77aa31c4b6" },
  "payload": {
    "invocation_id": "8a2f0e51-3c74-4b12-9f68-1d5c7e0a2b93",
    "decision": "deny",
    "matched_policy_version_ids": [
      "5e0b7c94-1a2d-4f83-b6c9-7d21e0a4f358",
      "c41a8f36-9d70-4e2b-a5f1-3b8c6d90e217"
    ],
    "conflict_resolution": "explicit deny overrides broader allow",
    "applied_risk_level": "high",
    "requires_approval": false,
    "reason": "Policy 'finance-no-write' denies write access to erp.invoice for this agent version",
    "degraded_mode": false
  }
}
```

### `approval.requested`

```json
{
  "event_id": "0198f2c1-6c2e-7a31-9b31-2f5a1c9e4b72",
  "event_type": "approval.requested",
  "schema_version": 1,
  "organisation_id": "6f1a1d2e-0f7a-4a6f-9a1e-2c74f0b1a3c9",
  "occurred_at": "2026-10-13T09:20:04.113Z",
  "recorded_at": "2026-10-13T09:20:04.140Z",
  "correlation_id": "b21c9e44-77aa-4c15-9d02-8f3e6c1a5d27",
  "actor": { "type": "agent", "id": "9c1f0a7d-2b3e-4d18-8f52-0e77aa31c4b6" },
  "payload": {
    "approval_request_id": "f70c2b81-4d3a-4e59-8a17-2c9b0e6f3d41",
    "invocation_id": "d3b8a4f2-6e91-4c07-8b2a-5f1e7c90d246",
    "tool_id": "2a7c9e13-5b68-4f20-9d84-6e0a3c72b95f",
    "risk_level": "high",
    "required_approvals": 1,
    "expires_at": "2026-10-13T21:20:04Z"
  }
}
```

### `release.state_changed`

```json
{
  "event_id": "0198f2c1-6c2e-7a44-9b31-2f5a1c9e4b75",
  "event_type": "release.state_changed",
  "schema_version": 1,
  "organisation_id": "6f1a1d2e-0f7a-4a6f-9a1e-2c74f0b1a3c9",
  "occurred_at": "2026-10-13T11:02:55.004Z",
  "recorded_at": "2026-10-13T11:02:55.031Z",
  "correlation_id": "0f6b1e29-7c4d-4a83-9b52-1e3d7a90c6f2",
  "actor": { "type": "user", "id": "3d9a5b10-8e42-4f77-b0c1-6a2e9d4f5b18" },
  "payload": {
    "release_id": "b6d1f0a4-9c27-4e35-8a71-5d0b2e6c94f8",
    "agent_id": "1f4b8c02-7a39-4d56-9e10-3c5b7a2d8f64",
    "agent_version_id": "e2a7c93b-4f18-4b60-8d57-9a1c3e0b6d25",
    "from_state": "canary",
    "to_state": "rolled_back",
    "reason": "Elevated tool error rate during canary observation window"
  }
}
```

## Ordering and Delivery Guarantees

- Events are published in the order they were written to the outbox for a given
  aggregate. Consumers must not assume global ordering.
- Delivery is at-least-once. Consumers deduplicate on `event_id` before applying
  a projection.
- Outbox rows are only marked published after the consumer stream acknowledges
  them; a crash between publish and acknowledge results in redelivery, which
  deduplication absorbs.
- Dead-letter handling: after a configured attempt count, an event is parked
  with its last error and surfaced as a risk event rather than dropped.
