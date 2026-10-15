"""Tests for the gateway's inbound invocation route (T124).

The pipeline is the real one; only its stages are recording doubles, so the
status mapping from contracts/mcp-gateway.md is asserted against real
enforcement behaviour rather than a stub.
"""

from __future__ import annotations

import httpx
import pytest

from gov.gateway.app import create_app
from gov.gateway.pipeline import (
    ApprovalOutcome,
    EnforcementError,
    EnforcementPipeline,
    InvocationRequest,
    PolicyDecision,
    Stage,
    StageRecord,
)

PAYLOAD = {
    "agent_version_id": "agent-version-1",
    "tool_id": "tool-1",
    "idempotency_key": "key-1",
    "environment": "prod",
    "parameters_digest": "sha256:abc",
}


class _Ok:
    def authenticate(self, request: InvocationRequest) -> object:
        return {"subject": "agent-1"}

    def authorize(self, principal: object, request: InvocationRequest) -> None:
        return None

    def record(self, entry: StageRecord) -> None:
        return None

    def dispatch(
        self, principal: object, request: InvocationRequest, risk: str
    ) -> dict[str, object]:
        return {"result": "ok"}


class _Policy:
    def __init__(self, decision: PolicyDecision) -> None:
        self._decision = decision

    def decide(self, principal: object, request: InvocationRequest) -> PolicyDecision:
        return self._decision


class _RaisingPolicy:
    def __init__(self, error: EnforcementError) -> None:
        self._error = error

    def decide(self, principal: object, request: InvocationRequest) -> PolicyDecision:
        raise self._error


class _Approval:
    def __init__(self, outcome: ApprovalOutcome) -> None:
        self._outcome = outcome

    def check(
        self, principal: object, request: InvocationRequest, risk: str
    ) -> ApprovalOutcome:
        return self._outcome


def _pipeline(
    decision: PolicyDecision,
    approval: ApprovalOutcome | None = None,
) -> EnforcementPipeline:
    return EnforcementPipeline(
        authenticator=_Ok(),
        authorizer=_Ok(),
        policy_engine=_Policy(decision),
        approval_gate=_Approval(
            approval or ApprovalOutcome(state="approved", reason="not required")
        ),
        audit_sink=_Ok(),
        dispatcher=_Ok(),
    )


def _failing_pipeline() -> EnforcementPipeline:
    return EnforcementPipeline(
        authenticator=_Ok(),
        authorizer=_Ok(),
        policy_engine=_RaisingPolicy(
            EnforcementError(Stage.POLICY, "policy engine unreachable", degraded=True)
        ),
        approval_gate=_Approval(ApprovalOutcome(state="approved", reason="n/a")),
        audit_sink=_Ok(),
        dispatcher=_Ok(),
    )


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://gateway",
    )


async def test_an_allowed_invocation_returns_the_result_and_the_decision() -> None:
    pipeline = _pipeline(
        PolicyDecision(
            effect="allow",
            reason="allowed by policy versions ['pv1']",
            risk_level="low",
            matched_policy_version_ids=("pv1",),
        )
    )
    async with _client(create_app(pipeline)) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["result"] == {"result": "ok"}
    assert body["policy_decision"]["matched_policy_version_ids"] == ["pv1"]
    assert [stage["stage"] for stage in body["stages"]] == [
        "identity",
        "authorization",
        "policy",
        "risk",
        "approval",
        "audit_before",
        "dispatch",
        "audit_after",
    ]


async def test_a_policy_denial_returns_two_hundred_with_the_reason() -> None:
    pipeline = _pipeline(
        PolicyDecision(
            effect="deny",
            reason="explicit deny by policy versions ['pv2']",
            risk_level="high",
            matched_policy_version_ids=("pv2",),
        )
    )
    async with _client(create_app(pipeline)) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "denied"
    assert "pv2" in body["reason"]
    assert "result" not in body


async def test_a_high_risk_invocation_is_accepted_and_held() -> None:
    pipeline = _pipeline(
        PolicyDecision(effect="allow", reason="allowed", risk_level="high"),
        ApprovalOutcome(
            state="pending",
            reason="tool is high risk; an approval is required",
            approval_request_id="approval-1",
        ),
    )
    async with _client(create_app(pipeline)) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["approval_request_id"] == "approval-1"


async def test_a_rejected_approval_is_forbidden() -> None:
    pipeline = _pipeline(
        PolicyDecision(effect="allow", reason="allowed", risk_level="critical"),
        ApprovalOutcome(
            state="rejected",
            reason="amount exceeds the approved threshold",
            approval_request_id="approval-1",
        ),
    )
    async with _client(create_app(pipeline)) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 403
    assert response.json()["status"] == "rejected"


async def test_an_unavailable_policy_engine_returns_service_unavailable() -> None:
    async with _client(create_app(_failing_pipeline())) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "failed_closed"
    assert body["degraded"] is True


async def test_a_gateway_without_a_pipeline_refuses_every_invocation() -> None:
    async with _client(create_app()) as client:
        response = await client.post("/v1/invocations", json=PAYLOAD)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "enforcement_unavailable"
    assert body["detail"].startswith("the gateway has no enforcement pipeline")


async def test_health_reports_whether_enforcement_is_configured() -> None:
    pipeline = _pipeline(
        PolicyDecision(effect="allow", reason="allowed", risk_level="low")
    )
    async with _client(create_app(pipeline)) as client:
        configured = await client.get("/healthz")
    async with _client(create_app()) as client:
        unconfigured = await client.get("/healthz")

    assert configured.json()["enforcement"] == "configured"
    assert unconfigured.json()["enforcement"] == "unavailable"


@pytest.mark.parametrize(
    "missing", ["agent_version_id", "tool_id", "idempotency_key", "environment"]
)
async def test_a_malformed_request_is_rejected(missing: str) -> None:
    body = {key: value for key, value in PAYLOAD.items() if key != missing}
    async with _client(create_app()) as client:
        response = await client.post("/v1/invocations", json=body)
    assert response.status_code == 422
