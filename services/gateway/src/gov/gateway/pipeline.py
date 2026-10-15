"""The gateway enforcement pipeline.

Constitution Principle III and ADR-0003: every Agent tool call traverses
authentication, authorization, policy, risk classification, approval, audit and
dispatch, in that order, and none of it may be skipped.

The order *is* the control. Authentication before authorization prevents an
unauthenticated caller from probing permissions; policy before approval prevents
a denied call from ever occupying an approver's attention; audit before dispatch
means an execution cannot happen without a preceding record of why it was
allowed. The pipeline fails closed: if a stage cannot be evaluated, the call is
refused rather than allowed.

The stages are injected as protocols so the ordering and the failure semantics
are testable without a live policy engine, while the concrete adapters (OPA,
Vault, the runner) are supplied at wiring time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Stage(StrEnum):
    """The enforcement stages, in the order they must run."""

    IDENTITY = "identity"
    AUTHORIZATION = "authorization"
    POLICY = "policy"
    RISK = "risk"
    APPROVAL = "approval"
    AUDIT_BEFORE = "audit_before"
    DISPATCH = "dispatch"
    AUDIT_AFTER = "audit_after"


#: The fixed order. Any implementation must produce records in this order.
ENFORCEMENT_ORDER: tuple[Stage, ...] = (
    Stage.IDENTITY,
    Stage.AUTHORIZATION,
    Stage.POLICY,
    Stage.RISK,
    Stage.APPROVAL,
    Stage.AUDIT_BEFORE,
    Stage.DISPATCH,
    Stage.AUDIT_AFTER,
)


class Outcome(StrEnum):
    """The terminal outcome of an invocation attempt."""

    EXECUTED = "executed"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"
    FAILED_CLOSED = "failed_closed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class InvocationRequest:
    """What a caller asks the gateway to do."""

    agent_version_id: str
    tool_id: str
    idempotency_key: str
    environment: str
    parameters_digest: str
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One stage's contribution to the decision, for the audit trail."""

    stage: Stage
    outcome: str
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationResult:
    """The terminal result, including the stages that produced it."""

    outcome: Outcome
    reason: str
    stages: tuple[StageRecord, ...]
    degraded: bool = False
    approval_request_id: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def executed(self) -> bool:
        return self.outcome is Outcome.EXECUTED


class EnforcementError(Exception):
    """A stage refused the invocation.

    `degraded` marks a refusal caused by an unavailable dependency rather than a
    decision, which matters because an outage must be visible in the audit trail
    as a fail-closed denial rather than mistaken for a policy decision.
    """

    def __init__(
        self,
        stage: Stage,
        reason: str,
        *,
        degraded: bool = False,
    ) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.degraded = degraded


class Authenticator(Protocol):
    """Establishes who is calling."""

    def authenticate(self, request: InvocationRequest) -> Any: ...


class Authorizer(Protocol):
    """Decides whether the caller may reach this Tool at all."""

    def authorize(self, principal: Any, request: InvocationRequest) -> None: ...


class PolicyEngine(Protocol):
    """Returns the policy decision for the invocation."""

    def decide(self, principal: Any, request: InvocationRequest) -> Any: ...


class ApprovalGate(Protocol):
    """Reports whether a high-risk invocation may proceed."""

    def check(self, principal: Any, request: InvocationRequest, risk: str) -> Any: ...


class AuditSink(Protocol):
    """Records a stage outcome. Raising here fails the invocation closed."""

    def record(self, entry: StageRecord) -> None: ...


class Dispatcher(Protocol):
    """Executes the tool in the isolated runtime."""

    def dispatch(
        self, principal: Any, request: InvocationRequest, risk: str
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The policy engine's answer."""

    effect: str
    reason: str
    risk_level: str
    matched_policy_version_ids: tuple[str, ...] = ()
    degraded: bool = False

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """The approval gate's answer."""

    state: str
    reason: str
    approval_request_id: str | None = None

    @property
    def satisfies(self) -> bool:
        return self.state == "approved"

    @property
    def holds(self) -> bool:
        return self.state == "pending"


class EnforcementPipeline:
    """Runs one invocation through the enforcement chain."""

    def __init__(
        self,
        *,
        authenticator: Authenticator,
        authorizer: Authorizer,
        policy_engine: PolicyEngine,
        approval_gate: ApprovalGate,
        audit_sink: AuditSink,
        dispatcher: Dispatcher,
    ) -> None:
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._policy_engine = policy_engine
        self._approval_gate = approval_gate
        self._audit_sink = audit_sink
        self._dispatcher = dispatcher

    def run(self, request: InvocationRequest) -> InvocationResult:
        """Enforce the chain and, if permitted, dispatch the tool call."""
        stages: list[StageRecord] = []
        degraded = False

        try:
            principal = self._authenticator.authenticate(request)
            stages.append(StageRecord(Stage.IDENTITY, "ok"))

            self._authorizer.authorize(principal, request)
            stages.append(StageRecord(Stage.AUTHORIZATION, "ok"))

            decision = self._policy_engine.decide(principal, request)
            stages.append(
                StageRecord(
                    Stage.POLICY,
                    decision.effect,
                    reason=decision.reason,
                    detail={"matched": list(decision.matched_policy_version_ids)},
                )
            )
            if decision.degraded:
                degraded = True

            stages.append(StageRecord(Stage.RISK, decision.risk_level))

            if not decision.allowed:
                # A denial is a decision, not an outage, but it still must be
                # recorded before it is returned.
                self._audit(
                    stages, request, outcome="denied", reason=decision.reason
                )
                return InvocationResult(
                    outcome=Outcome.DENIED,
                    reason=decision.reason,
                    stages=tuple(stages),
                    degraded=degraded,
                )

            approval = self._approval_gate.check(principal, request, decision.risk_level)
            stages.append(
                StageRecord(Stage.APPROVAL, approval.state, reason=approval.reason)
            )
            if approval.holds:
                self._audit(
                    stages, request, outcome="pending_approval", reason=approval.reason
                )
                return InvocationResult(
                    outcome=Outcome.PENDING_APPROVAL,
                    reason=approval.reason,
                    stages=tuple(stages),
                    degraded=degraded,
                    approval_request_id=approval.approval_request_id,
                )
            if not approval.satisfies:
                self._audit(
                    stages, request, outcome="rejected", reason=approval.reason
                )
                return InvocationResult(
                    outcome=Outcome.REJECTED,
                    reason=approval.reason,
                    stages=tuple(stages),
                    degraded=degraded,
                    approval_request_id=approval.approval_request_id,
                )

            # Auditing before dispatch is what makes "no execution without a
            # record of why" true rather than merely intended.
            self._audit(stages, request, outcome="allowed", reason=None)

            payload = self._dispatcher.dispatch(principal, request, decision.risk_level)
            stages.append(StageRecord(Stage.DISPATCH, "ok"))

            self._audit(stages, request, outcome="executed", reason=None, sink_only=True)

            return InvocationResult(
                outcome=Outcome.EXECUTED,
                reason="executed",
                stages=tuple(stages),
                degraded=degraded,
                payload=payload,
            )

        except EnforcementError as refusal:
            # A refusal is either a decision (identity, authorization) or a
            # fail-closed reaction to an unavailable dependency. Those are
            # different outcomes and must not be conflated in the audit trail.
            stages.append(
                StageRecord(
                    refusal.stage,
                    "failed",
                    reason=refusal.reason,
                    detail={"degraded": refusal.degraded},
                )
            )
            outcome = Outcome.FAILED_CLOSED if refusal.degraded else Outcome.DENIED
            self._try_audit(
                StageRecord(
                    Stage.AUDIT_AFTER,
                    outcome.value,
                    reason=refusal.reason,
                    detail={"stage": refusal.stage.value, "degraded": refusal.degraded},
                )
            )
            return InvocationResult(
                outcome=outcome,
                reason=refusal.reason,
                stages=tuple(stages),
                degraded=refusal.degraded,
            )

    def _audit(
        self,
        stages: list[StageRecord],
        request: InvocationRequest,
        *,
        outcome: str,
        reason: str | None,
        sink_only: bool = False,
    ) -> None:
        entry = StageRecord(
            Stage.AUDIT_BEFORE if not sink_only else Stage.AUDIT_AFTER,
            outcome,
            reason=reason,
            detail={"idempotency_key": request.idempotency_key},
        )
        try:
            self._audit_sink.record(entry)
        except Exception as exc:
            raise EnforcementError(
                Stage.AUDIT_BEFORE,
                f"audit sink unavailable: {exc}",
                degraded=True,
            ) from exc
        stages.append(entry)

    def _try_audit(self, entry: StageRecord) -> None:
        """Best-effort audit of a refusal, so an outage is still visible."""
        try:
            self._audit_sink.record(entry)
        except Exception:
            return
