"""Unit tests for the gateway enforcement chain (T053).

The stages are replaced by recording doubles so the *order* of enforcement and
the *failure semantics* are asserted directly. Nothing here tests a real OPA or
a live runner; those are the Phase 0 / Phase 4 integration steps.
"""

from __future__ import annotations

import httpx

from gov.gateway.app import create_app
from gov.gateway.pipeline import (
    ENFORCEMENT_ORDER,
    ApprovalOutcome,
    EnforcementError,
    EnforcementPipeline,
    InvocationRequest,
    Outcome,
    PolicyDecision,
    Stage,
    StageRecord,
)


class Recorder:
    """Collects the order of stage entry and the audit entries raised."""

    def __init__(self) -> None:
        self.order: list[Stage] = []
        self.audit: list[StageRecord] = []
        self.dispatched: list[InvocationRequest] = []


class FakeAuthenticator:
    def __init__(self, recorder: Recorder, error: EnforcementError | None = None) -> None:
        self._recorder = recorder
        self._error = error

    def authenticate(self, request: InvocationRequest) -> object:
        self._recorder.order.append(Stage.IDENTITY)
        if self._error:
            raise self._error
        return {"subject": "agent-1", "organisation_id": "org-1"}


class FakeAuthorizer:
    def __init__(self, recorder: Recorder, error: EnforcementError | None = None) -> None:
        self._recorder = recorder
        self._error = error

    def authorize(self, principal: object, request: InvocationRequest) -> None:
        self._recorder.order.append(Stage.AUTHORIZATION)
        if self._error:
            raise self._error


class FakePolicyEngine:
    def __init__(
        self,
        recorder: Recorder,
        decision: PolicyDecision | None = None,
        error: EnforcementError | None = None,
    ) -> None:
        self._recorder = recorder
        self._decision = decision or PolicyDecision(
            effect="allow", reason="matched policy pv1", risk_level="low"
        )
        self._error = error

    def decide(self, principal: object, request: InvocationRequest) -> PolicyDecision:
        self._recorder.order.append(Stage.POLICY)
        if self._error:
            raise self._error
        return self._decision


class FakeApprovalGate:
    def __init__(self, recorder: Recorder, outcome: ApprovalOutcome | None = None) -> None:
        self._recorder = recorder
        self._outcome = outcome or ApprovalOutcome(state="approved", reason="not required")

    def check(
        self, principal: object, request: InvocationRequest, risk: str
    ) -> ApprovalOutcome:
        self._recorder.order.append(Stage.APPROVAL)
        return self._outcome


class FakeAuditSink:
    def __init__(self, recorder: Recorder, fail: bool = False) -> None:
        self._recorder = recorder
        self._fail = fail

    def record(self, entry: StageRecord) -> None:
        self._recorder.audit.append(entry)
        if self._fail and entry.outcome in ("allowed", "executed"):
            raise RuntimeError("audit sink is unreachable")


class FakeDispatcher:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    def dispatch(
        self, principal: object, request: InvocationRequest, risk: str
    ) -> dict[str, object]:
        self._recorder.order.append(Stage.DISPATCH)
        self._recorder.dispatched.append(request)
        return {"result": "ok"}


def _pipeline(
    recorder: Recorder,
    *,
    policy: FakePolicyEngine | None = None,
    approval: FakeApprovalGate | None = None,
    authorizer: FakeAuthorizer | None = None,
    authenticator: FakeAuthenticator | None = None,
    audit: FakeAuditSink | None = None,
) -> EnforcementPipeline:
    return EnforcementPipeline(
        authenticator=authenticator or FakeAuthenticator(recorder),
        authorizer=authorizer or FakeAuthorizer(recorder),
        policy_engine=policy or FakePolicyEngine(recorder),
        approval_gate=approval or FakeApprovalGate(recorder),
        audit_sink=audit or FakeAuditSink(recorder),
        dispatcher=FakeDispatcher(recorder),
    )


def _request() -> InvocationRequest:
    return InvocationRequest(
        agent_version_id="agent-version-1",
        tool_id="tool-1",
        idempotency_key="key-1",
        environment="prod",
        parameters_digest="sha256:abc",
    )


def test_a_permitted_invocation_runs_every_stage_in_order() -> None:
    recorder = Recorder()
    result = _pipeline(recorder).run(_request())

    assert result.outcome is Outcome.EXECUTED
    assert result.executed is True
    assert result.payload == {"result": "ok"}
    assert recorder.order == [
        Stage.IDENTITY,
        Stage.AUTHORIZATION,
        Stage.POLICY,
        Stage.APPROVAL,
        Stage.DISPATCH,
    ]
    assert result.degraded is False


def test_the_stage_records_follow_the_declared_enforcement_order() -> None:
    recorder = Recorder()
    result = _pipeline(recorder).run(_request())
    assert tuple(record.stage for record in result.stages) == ENFORCEMENT_ORDER


def test_audit_is_written_before_dispatch_and_after_execution() -> None:
    recorder = Recorder()
    _pipeline(recorder).run(_request())
    assert [entry.outcome for entry in recorder.audit] == ["allowed", "executed"]


def test_a_denied_invocation_never_dispatches() -> None:
    recorder = Recorder()
    policy = FakePolicyEngine(
        recorder,
        decision=PolicyDecision(
            effect="deny",
            reason="explicit deny by policy version pv2",
            risk_level="high",
            matched_policy_version_ids=("pv2",),
        ),
    )
    result = _pipeline(recorder, policy=policy).run(_request())

    assert result.outcome is Outcome.DENIED
    assert result.reason == "explicit deny by policy version pv2"
    assert recorder.dispatched == []
    assert [entry.outcome for entry in recorder.audit] == ["denied"]
    assert recorder.audit[0].reason is not None


def test_an_unauthorized_caller_is_denied_not_failed_closed() -> None:
    recorder = Recorder()
    authorizer = FakeAuthorizer(
        recorder,
        error=EnforcementError(Stage.AUTHORIZATION, "role may not invoke this tool"),
    )
    result = _pipeline(recorder, authorizer=authorizer).run(_request())

    assert result.outcome is Outcome.DENIED
    assert result.degraded is False
    assert recorder.dispatched == []


def test_high_risk_invocation_is_held_for_approval() -> None:
    recorder = Recorder()
    policy = FakePolicyEngine(
        recorder,
        decision=PolicyDecision(effect="allow", reason="allowed", risk_level="high"),
    )
    approval = FakeApprovalGate(
        recorder,
        outcome=ApprovalOutcome(
            state="pending",
            reason="tool is high risk; an approval is required",
            approval_request_id="approval-1",
        ),
    )
    result = _pipeline(recorder, policy=policy, approval=approval).run(_request())

    assert result.outcome is Outcome.PENDING_APPROVAL
    assert result.approval_request_id == "approval-1"
    assert recorder.dispatched == []
    assert [entry.outcome for entry in recorder.audit] == ["pending_approval"]


def test_a_rejected_approval_never_executes() -> None:
    recorder = Recorder()
    policy = FakePolicyEngine(
        recorder,
        decision=PolicyDecision(effect="allow", reason="allowed", risk_level="critical"),
    )
    approval = FakeApprovalGate(
        recorder,
        outcome=ApprovalOutcome(
            state="rejected",
            reason="amount exceeds the approved threshold",
            approval_request_id="approval-1",
        ),
    )
    result = _pipeline(recorder, policy=policy, approval=approval).run(_request())

    assert result.outcome is Outcome.REJECTED
    assert recorder.dispatched == []


def test_an_unavailable_policy_engine_fails_closed() -> None:
    """The behavioural core of the fail-closed requirement (quickstart V9)."""
    recorder = Recorder()
    policy = FakePolicyEngine(
        recorder,
        error=EnforcementError(
            Stage.POLICY, "policy engine unreachable", degraded=True
        ),
    )
    result = _pipeline(recorder, policy=policy).run(_request())

    assert result.outcome is Outcome.FAILED_CLOSED
    assert result.degraded is True
    assert recorder.dispatched == []
    assert recorder.audit[-1].outcome == "failed_closed"
    assert recorder.audit[-1].detail["degraded"] is True


def test_an_unavailable_audit_sink_fails_closed_before_dispatch() -> None:
    recorder = Recorder()
    result = _pipeline(recorder, audit=FakeAuditSink(recorder, fail=True)).run(_request())

    assert result.outcome is Outcome.FAILED_CLOSED
    assert result.degraded is True
    assert recorder.dispatched == []


def test_an_unavailable_identity_provider_fails_closed() -> None:
    recorder = Recorder()
    authenticator = FakeAuthenticator(
        recorder,
        error=EnforcementError(Stage.IDENTITY, "identity provider unreachable", degraded=True),
    )
    result = _pipeline(recorder, authenticator=authenticator).run(_request())

    assert result.outcome is Outcome.FAILED_CLOSED
    assert recorder.dispatched == []


def test_enforcement_order_covers_every_stage_exactly_once() -> None:
    assert len(set(ENFORCEMENT_ORDER)) == len(ENFORCEMENT_ORDER)
    assert ENFORCEMENT_ORDER[0] is Stage.IDENTITY
    assert ENFORCEMENT_ORDER[-1] is Stage.AUDIT_AFTER


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://gateway",
    )


async def test_gateway_liveness_probe() -> None:
    async with _client(create_app()) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "enforcement": "unavailable"}
