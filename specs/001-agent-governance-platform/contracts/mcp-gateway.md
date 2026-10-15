# MCP Gateway Invocation Contract

**Feature**: `001-agent-governance-platform`
**Component**: `services/gateway`
**Status**: design contract (implementation begins after Phase 0 spike)

The gateway is the only path from an Agent to a Tool. This document defines the
behaviour a caller may rely on, and the behaviour the gateway must guarantee
regardless of implementation. It deliberately specifies observable behaviour
rather than internal structure.

## Enforcement Order

Every invocation must pass through these stages in order. A stage that cannot be
completed successfully terminates the invocation. Stages are not reorderable and
none may be skipped.

```text
1. authN   verify caller identity (agent identity + human principal context)
2. authZ   verify the caller's role and scope permit the requested action
3. policy  obtain a decision from OPA for this (agent_version, tool, env)
4. risk    classify from the tool's risk level and any per-invocation escalation
5. approval  high/critical risk: hold until a recorded approval exists
6. audit   emit the pre-execution audit event
7. dispatch  invoke the tool through the isolated runner
8. audit   emit the post-execution audit event with the outcome
```

Stages 6 and 8 are non-negotiable: if the audit sink is unreachable the
invocation is denied rather than executed unaudited. Stage 3 failing closed means
denial, not a default grant.

## Invocation Request

The caller (an Agent runtime) supplies:

| Field | Required | Notes |
|-------|----------|-------|
| `agent_version_id` | yes | Must reference a `released` version |
| `tool_id` | yes | Must reference an `active` tool |
| `idempotency_key` | yes | Caller-scoped; makes retries safe |
| `parameters` | yes | Validated against the tool permission set before dispatch |
| `environment` | yes | e.g. `prod`, `staging`; part of the policy input |
| `correlation_id` | no | Supplied by the caller to group a multi-step workflow |
| `human_context` | conditional | Required when the operation acts on behalf of a person |

## Responses

| Status | Meaning | Caller action |
|--------|---------|---------------|
| `200 allowed` | Executed; result included | Proceed |
| `200 denied` | Policy denied, with reason and matched policies | Do not retry without a policy change; the denial is recorded |
| `202 pending_approval` | Held for human decision | Wait, then poll the approval request; do not re-issue with a new idempotency key |
| `200 replayed` | A previous invocation with the same idempotency key exists | Treat the returned outcome as the result of this call |
| `403 forbidden` | Caller not permitted by role or scope | Do not retry |
| `404 unknown_target` | Unknown, retired or non-active Agent, version or Tool | Do not retry |
| `409 conflict` | Tool risk level changed while the request was in flight | Re-evaluate the request |
| `503 unavailable` | A dependency on the enforcement path failed | Fail closed; the denial is recorded as degraded mode |

### Denied response shape

```json
{
  "invocation_id": "8a2f0e51-3c74-4b12-9f68-1d5c7e0a2b93",
  "status": "denied",
  "correlation_id": "b21c9e44-77aa-4c15-9d02-8f3e6c1a5d27",
  "decision": {
    "effect": "deny",
    "applied_risk_level": "high",
    "matched_policy_version_ids": [
      "5e0b7c94-1a2d-4f83-b6c9-7d21e0a4f358"
    ],
    "reason": "Policy 'finance-no-write' denies write access to erp.invoice for this agent version",
    "degraded_mode": false
  }
}
```

### Pending approval response shape

```json
{
  "invocation_id": "d3b8a4f2-6e91-4c07-8b2a-5f1e7c90d246",
  "status": "pending_approval",
  "correlation_id": "b21c9e44-77aa-4c15-9d02-8f3e6c1a5d27",
  "approval_request_id": "f70c2b81-4d3a-4e59-8a17-2c9b0e6f3d41",
  "expires_at": "2026-10-13T21:20:04Z",
  "decision": {
    "effect": "allow",
    "applied_risk_level": "high",
    "requires_approval": true,
    "reason": "Tool is classified high risk; a recorded approval is required before execution"
  }
}
```

## Guarantees

1. **No ungoverned path.** A tool adapter is reachable only through the gateway.
   The runner accepts dispatch only from the gateway's workload identity.
2. **Fail closed.** If OPA, the approval store or the audit sink is unavailable,
   the invocation is denied and the denial is recorded with
   `degraded_mode: true`.
3. **At most one execution per idempotency key.** A replay returns the original
   outcome, including a `pending_approval` outcome — it does not raise a second
   approval request.
4. **Approvals are single-use.** An approved request authorises exactly one
   invocation and cannot be replayed for a second execution.
5. **Audit completeness.** Every attempt, including denials, timeouts and
   degraded-mode rejections, produces an audit event with a reason.
6. **Risk escalation is respected.** If a tool's risk level rises while a
   request is pending, the request is re-evaluated rather than completed under
   the previous classification.

## Tool Dispatch and Isolation

- Low and medium risk tools dispatch to the shared runner pool with a restricted
  filesystem, dropped capabilities and an explicit egress allow-list.
- High and critical risk tools dispatch to a dedicated sandbox per execution:
  no ambient credentials, read-only root filesystem, seccomp profile, and no
  default egress. On Kubernetes these run on a separate node pool with a
  distinct runtime class.
- The runner receives short-lived, narrowly scoped credentials minted for the
  single execution and revoked when it ends. It never holds database
  credentials and never writes to governance state directly.

## Non-Goals

- The gateway does not author or evaluate policy itself; it asks OPA and records
  the answer, including which policy version produced it.
- The gateway does not decide risk classification; it applies the classification
  recorded against the Tool and any per-invocation escalation rule.
- The gateway does not store approvals; it reads the approval state from the
  control plane and waits for a recorded decision.
