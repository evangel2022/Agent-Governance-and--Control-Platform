"""Unit tests for sensitive-data redaction (T107, FR-040)."""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from gov.api.infrastructure.redaction import (
    REDACTED,
    LogRedactionFilter,
    RedactingTelemetrySink,
    Redactor,
    TelemetryEvent,
)
from gov.api.interface.errors import ValidationProblem
from gov.api.main import create_app


@pytest.fixture
def redactor() -> Redactor:
    return Redactor(
        sensitive_keys=frozenset({"account_number"}),
        value_patterns=(re.compile(r"GB[0-9]{2}[A-Z0-9]{10}"),),
    )


def test_a_sensitive_key_is_replaced_wholesale(redactor: Redactor) -> None:
    assert redactor.redact({"password": "hunter2"}) == {"password": REDACTED}
    assert redactor.redact({"api_key": "abc"}) == {"api_key": REDACTED}
    assert redactor.redact({"Authorization": "Bearer x"}) == {"Authorization": REDACTED}


def test_explicitly_declared_keys_are_redacted(redactor: Redactor) -> None:
    assert redactor.redact({"account_number": "12345678"}) == {
        "account_number": REDACTED
    }


def test_ordinary_values_are_untouched(redactor: Redactor) -> None:
    payload = {"tool_id": "tool-1", "risk_level": "high", "count": 3}
    assert redactor.redact(payload) == payload


def test_nested_structures_are_walked(redactor: Redactor) -> None:
    payload = {
        "invocation": {"parameters": {"token": "t-1", "invoice_id": "inv-7"}},
        "evidence": [{"secret": "s"}, {"note": "ok"}],
    }
    redacted = redactor.redact(payload)
    assert redacted["invocation"]["parameters"]["token"] == REDACTED
    assert redacted["invocation"]["parameters"]["invoice_id"] == "inv-7"
    assert redacted["evidence"][0]["secret"] == REDACTED
    assert redacted["evidence"][1]["note"] == "ok"


def test_value_patterns_scrub_free_text(redactor: Redactor) -> None:
    text = "transfer to GB29NWBK60161331926819 was rejected"
    redacted = redactor.redact(text)
    assert "GB29NWBK60161331926819" not in redacted
    assert REDACTED in redacted


def test_redaction_does_not_mutate_the_input(redactor: Redactor) -> None:
    payload = {"token": "t-1"}
    redactor.redact(payload)
    assert payload == {"token": "t-1"}


def test_log_filter_scrubs_the_rendered_message(redactor: Redactor) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("gov.test.redaction")
    logger.handlers = [handler]
    logger.addFilter(LogRedactionFilter(redactor))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("settling account GB29NWBK60161331926819")

    emitted = stream.getvalue()
    assert "GB29NWBK60161331926819" not in emitted
    assert REDACTED in emitted
    logger.removeFilter(logger.filters[0])
    logger.handlers = []


def test_log_filter_scrubs_structured_extras(redactor: Redactor) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(api_key)s"))
    logger = logging.getLogger("gov.test.redaction.extra")
    logger.handlers = [handler]
    logger.addFilter(LogRedactionFilter(redactor))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("calling vendor", extra={"api_key": "super-secret"})

    emitted = stream.getvalue()
    assert "super-secret" not in emitted
    assert REDACTED in emitted
    logger.filters.clear()
    logger.handlers = []


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)


def test_telemetry_sink_redacts_attributes_before_export(redactor: Redactor) -> None:
    inner = _RecordingSink()
    sink = RedactingTelemetrySink(inner=inner, redactor=redactor)

    sink.emit(
        TelemetryEvent(
            name="policy.decision",
            attributes={
                "tool_id": "tool-1",
                "api_key": "abc",
                "note": "account GB29NWBK60161331926819",
            },
        )
    )

    emitted = inner.events[0].attributes
    assert emitted["tool_id"] == "tool-1"
    assert emitted["api_key"] == REDACTED
    assert "GB29NWBK60161331926819" not in str(emitted["note"])


def test_telemetry_sink_preserves_the_event_name(redactor: Redactor) -> None:
    inner = _RecordingSink()
    RedactingTelemetrySink(inner=inner, redactor=redactor).emit(
        TelemetryEvent(name="invocation.completed", attributes={})
    )
    assert inner.events[0].name == "invocation.completed"


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def test_problem_details_do_not_echo_credential_like_fields() -> None:
    """The default application redacts sensitive keys inside error payloads."""
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise ValidationProblem(
            "tool registration rejected",
            errors=[
                {
                    "field": "adapter_ref",
                    "message": "invalid",
                    "password": "hunter2",
                }
            ],
        )

    async with _client(app) as client:
        response = await client.get("/boom")

    body: dict[str, Any] = response.json()
    assert response.status_code == 422
    assert body["detail"] == "tool registration rejected"
    assert body["errors"][0]["password"] == REDACTED
    assert "hunter2" not in response.text


async def test_a_configured_redactor_scrubs_problem_text() -> None:
    app = create_app()
    redactor = Redactor(value_patterns=(re.compile(r"GB[0-9]{2}[A-Z0-9]{10}"),))

    @app.get("/boom")
    async def boom() -> None:
        raise ValidationProblem("transfer GB29NWBK60161331926819 was rejected")

    from gov.api.interface.errors import register_problem_handlers

    register_problem_handlers(app, redactor=redactor.redact)

    async with _client(app) as client:
        response = await client.get("/boom")

    assert "GB29NWBK60161331926819" not in response.text
    assert REDACTED in response.text
