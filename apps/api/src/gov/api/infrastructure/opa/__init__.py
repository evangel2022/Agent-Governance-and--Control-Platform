"""Policy engine adapters."""

from gov.api.application.permission.decision import build_authorization_input
from gov.api.application.ports import AuthorizationDecision, DecisionUnavailable
from gov.api.infrastructure.opa.authorization import (
    DECISION_PATH,
    OpaAuthorizationClient,
)

__all__ = [
    "DECISION_PATH",
    "AuthorizationDecision",
    "DecisionUnavailable",
    "OpaAuthorizationClient",
    "build_authorization_input",
]
