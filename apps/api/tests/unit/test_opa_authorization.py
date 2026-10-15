"""Unit tests for the authorization decision client (T010).

The policy engine is exercised through a stub transport: a double for the
external service, never for the code under test. The client's assembly, parsing
and failure behaviour are the real ones.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from gov.api.infrastructure.opa.authorization import (
    DECISION_PATH,
    DecisionUnavailable,
    OpaAuthorizationClient,
    build_authorization_input,
)


def _client(handler: Any) -> OpaAuthorizationClient:
    # The caller supplies the engine's address; the client only knows the path.
    transport = httpx.MockTransport(handler)
    return OpaAuthorizationClient(
        client=httpx.AsyncClient(transport=transport, base_url="http://policy-engine")
    )


def _decision_response(allowed: bool, reason: str = "granted", sources: Any = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "allowed": allowed,
                    "reason": reason,
                    "sources": sources if sources is not None else [],
                }
            },
        )

    return handler


# ------------------------------------------------------------------- input


def test_the_input_carries_every_coordinate_and_its_schema_version() -> None:
    document = build_authorization_input(
        organisation_id="org-1",
        user_id="user-1",
        permission="registry.write",
        permissions=("registry.write", "registry.read"),
        roles=({"id": "role-1", "name": "Owner"},),
        resource={"type": "agent", "id": "agent-9", "owner_user_id": "user-1"},
        requires_resource_accountability=True,
        requested_at="2026-10-14T09:00:00Z",
    )

    assert document["schema_version"] == 1
    assert document["organisation_id"] == "org-1"
    assert document["user_id"] == "user-1"
    assert document["permission"] == "registry.write"
    # Sorted, so the same grants always produce the same document.
    assert document["permissions"] == ["registry.read", "registry.write"]
    assert document["roles"] == [{"id": "role-1", "name": "Owner"}]
    assert document["requires_resource_accountability"] is True
    assert document["resource"] == {
        "type": "agent",
        "id": "agent-9",
        "owner_user_id": "user-1",
    }


def test_the_input_defaults_are_safe() -> None:
    document = build_authorization_input(
        organisation_id="org-1",
        user_id="user-1",
        permission="registry.read",
        permissions=(),
    )
    assert document["resource"] is None
    assert document["roles"] == []
    assert document["requires_resource_accountability"] is False
    assert document["context"] == {}


async def test_the_client_sends_the_input_under_the_expected_key() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200, json={"result": {"allowed": True, "reason": "granted", "sources": []}}
        )

    await _client(handler).decide({"permission": "registry.read"})

    assert captured["path"] == DECISION_PATH
    assert '"input"' in captured["body"]
    assert "registry.read" in captured["body"]


# ---------------------------------------------------------------- decisions


async def test_an_allowed_decision_is_returned_with_its_sources() -> None:
    client = _client(
        _decision_response(True, "granted by ['rbac']", ["rbac.permission_granted"])
    )
    decision = await client.decide({"permission": "registry.read"})

    assert decision.allowed is True
    assert decision.effect == "allow"
    assert decision.sources == ("rbac.permission_granted",)
    assert decision.degraded is False


async def test_a_denied_decision_is_returned_with_its_reason() -> None:
    client = _client(
        _decision_response(
            False,
            "denied by ['abac.resource_accountability']",
            ["abac.resource_accountability"],
        )
    )
    decision = await client.decide({"permission": "registry.write"})

    assert decision.allowed is False
    assert decision.effect == "deny"
    assert "accountability" in decision.reason


async def test_a_transport_failure_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(DecisionUnavailable):
        await _client(handler).decide({"permission": "registry.read"})


async def test_a_non_success_status_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="engine error")

    with pytest.raises(DecisionUnavailable):
        await _client(handler).decide({"permission": "registry.read"})


async def test_a_non_json_body_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(DecisionUnavailable):
        await _client(handler).decide({"permission": "registry.read"})


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"result": None},
        {"result": {"reason": "granted"}},
        {"result": {"allowed": "yes", "reason": "granted"}},
        {"result": {"allowed": True, "reason": 7}},
    ],
)
async def test_a_malformed_decision_fails_closed(body: Any) -> None:
    """Guessing at an unclear answer would mean guessing about access."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(DecisionUnavailable):
        await _client(handler).decide({"permission": "registry.read"})


async def test_non_list_sources_do_not_break_the_decision() -> None:
    client = _client(_decision_response(True, sources="rbac"))
    decision = await client.decide({"permission": "registry.read"})
    assert decision.allowed is True
    assert decision.sources == ()
