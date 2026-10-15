"""The authorization decision adapter.

ADR-0011 makes the policy engine the single authorization authority. This module
is the adapter that reaches it: it posts the input document the application
assembled and turns the engine's answer into the decision the application acts
on. The decision type and the failure type belong to the port in
`gov.api.application.ports`, not here, because a caller must be able to name them
without importing an adapter.

**It fails closed.** A transport error, a timeout, a non-success status or a
malformed body raises `DecisionUnavailable`. The caller refuses the request and
records it as a degraded refusal, so an outage can never be mistaken for
permission. Returning a deny instead would hide the outage inside a
legitimate-looking denial, which is the failure mode this design exists to avoid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from gov.api.application.permission.decision import build_authorization_input
from gov.api.application.ports import AuthorizationDecision, DecisionUnavailable

#: The document path of the decision rule in `deploy/policy/authorization.rego`.
DECISION_PATH = "/v1/data/gov/authorization/decision"

__all__ = [
    "DECISION_PATH",
    "AuthorizationDecision",
    "DecisionUnavailable",
    "OpaAuthorizationClient",
    "build_authorization_input",
]


@dataclass
class OpaAuthorizationClient:
    """Queries the policy engine for an authorization decision."""

    client: httpx.AsyncClient
    path: str = DECISION_PATH
    timeout_seconds: float = 2.0

    async def decide(self, decision_input: Mapping[str, Any]) -> AuthorizationDecision:
        """Return the decision for an input document.

        Raises:
            DecisionUnavailable: on any failure to obtain a well-formed answer.
        """
        try:
            response = await self.client.post(
                self.path,
                json={"input": dict(decision_input)},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DecisionUnavailable(f"policy engine unreachable: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            raise DecisionUnavailable(
                f"policy engine returned status {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DecisionUnavailable("policy engine returned a non-JSON body") from exc

        return _parse(body)


def _parse(body: Any) -> AuthorizationDecision:
    """Turn a policy engine response into a decision, or refuse it.

    A response that does not clearly say allow or deny is treated as unavailable
    rather than guessed at, because guessing here would mean guessing about
    access.
    """
    if not isinstance(body, Mapping) or "result" not in body:
        raise DecisionUnavailable("policy engine response has no decision")
    result = body["result"]
    if not isinstance(result, Mapping):
        raise DecisionUnavailable("policy engine decision is not an object")

    allowed = result.get("allowed")
    reason = result.get("reason")
    if not isinstance(allowed, bool) or not isinstance(reason, str):
        raise DecisionUnavailable("policy engine decision is malformed")

    raw_sources = result.get("sources", [])
    sources = (
        tuple(str(item) for item in raw_sources)
        if isinstance(raw_sources, list)
        else ()
    )
    return AuthorizationDecision(allowed=allowed, reason=reason, sources=sources)
