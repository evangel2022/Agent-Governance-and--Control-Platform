"""The gateway's inbound invocation route.

Implements the request/response contract in `contracts/mcp-gateway.md` on top of
the enforcement pipeline. The status mapping is deliberate:

| Pipeline outcome | HTTP | Why |
|------------------|------|-----|
| executed         | 200  | allowed and completed |
| denied           | 200  | a policy decision is an answer, not a transport failure |
| pending_approval | 202  | accepted, held for a human decision |
| rejected         | 403  | a refused approval is terminal; do not retry |
| failed_closed    | 503  | an enforcement dependency was unavailable |

With no pipeline configured the route refuses every invocation, because a gateway
that cannot enforce must not allow. That is the fail-closed principle expressed
as an HTTP behaviour rather than a comment.

The RFC 9457 helper is a few lines rather than a shared import: the gateway is a
separately deployed process and must not depend on the control-plane package.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gov.gateway.pipeline import (
    EnforcementPipeline,
    InvocationRequest,
    InvocationResult,
    Outcome,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"

OUTCOME_STATUS: dict[Outcome, int] = {
    Outcome.EXECUTED: status.HTTP_200_OK,
    Outcome.DENIED: status.HTTP_200_OK,
    Outcome.PENDING_APPROVAL: status.HTTP_202_ACCEPTED,
    Outcome.REJECTED: status.HTTP_403_FORBIDDEN,
    Outcome.FAILED_CLOSED: status.HTTP_503_SERVICE_UNAVAILABLE,
}


class InvocationBody(BaseModel):
    """The caller's request, mirroring contracts/mcp-gateway.md."""

    agent_version_id: str = Field(min_length=1, max_length=200)
    tool_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=100)
    parameters_digest: str = Field(min_length=1, max_length=200)
    correlation_id: str | None = None


def _problem(*, http_status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": "about:blank",
            "title": title,
            "status": http_status,
            "code": code,
            "detail": detail,
        },
    )


def _body(result: InvocationResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.outcome.value,
        "reason": result.reason,
        "degraded": result.degraded,
        "approval_request_id": result.approval_request_id,
        "stages": [
            {
                "stage": record.stage.value,
                "outcome": record.outcome,
                "reason": record.reason,
            }
            for record in result.stages
        ],
    }
    decision = next(
        (record for record in result.stages if record.stage.value == "policy"), None
    )
    if decision is not None:
        payload["policy_decision"] = {
            "effect": decision.outcome,
            "reason": decision.reason,
            "matched_policy_version_ids": list(decision.detail.get("matched", [])),
        }
    if result.payload is not None:
        payload["result"] = result.payload
    return payload


def create_router(pipeline: EnforcementPipeline | None) -> APIRouter:
    """Build the invocation router, optionally bound to an enforcement pipeline."""
    router = APIRouter(tags=["Invocation"])

    @router.post("/v1/invocations")
    async def invoke(body: InvocationBody, request: Request) -> JSONResponse:
        if pipeline is None:
            # Fail closed: no pipeline means no enforcement, so nothing runs.
            return _problem(
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="enforcement_unavailable",
                title="Enforcement unavailable",
                detail=(
                    "the gateway has no enforcement pipeline configured, so the "
                    "invocation is refused rather than executed unaudited"
                ),
            )

        result = pipeline.run(
            InvocationRequest(
                agent_version_id=body.agent_version_id,
                tool_id=body.tool_id,
                idempotency_key=body.idempotency_key,
                environment=body.environment,
                parameters_digest=body.parameters_digest,
                correlation_id=body.correlation_id,
            )
        )
        return JSONResponse(
            status_code=OUTCOME_STATUS[result.outcome],
            content=_body(result),
        )

    return router


def install(app: Any, pipeline: EnforcementPipeline | None) -> None:
    """Attach the invocation route and the enforcement liveness detail."""
    app.include_router(create_router(pipeline))
    app.state.enforcement_configured = pipeline is not None
