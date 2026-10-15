"""Unit tests for the application factory and RFC 9457 error contract (T027)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from gov.api.interface.errors import PROBLEM_MEDIA_TYPE, NotFoundProblem
from gov.api.main import create_app


@pytest.fixture
def app() -> FastAPI:
    application = create_app()

    @application.get("/v1/things/{thing_id}")
    async def get_thing(thing_id: str, page_size: int = 50) -> dict[str, object]:
        if thing_id == "missing":
            raise NotFoundProblem("no such thing")
        return {"id": thing_id, "page_size": page_size}

    return application


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def test_health_endpoint_is_available(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_not_found_uses_problem_details(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/v1/things/missing")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["status"] == 404
    assert body["code"] == "not_found"
    assert body["title"] == "Not found"
    assert body["detail"] == "no such thing"
    assert body["instance"] == "/v1/things/missing"


async def test_validation_failure_names_the_offending_field(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/v1/things/ok", params={"page_size": "not-a-number"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "validation_error"
    fields = {item["field"] for item in body["errors"]}
    assert "page_size" in fields


async def test_valid_request_is_unaffected(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/v1/things/ok", params={"page_size": 5})
    assert response.status_code == 200
    assert response.json() == {"id": "ok", "page_size": 5}


async def test_openapi_document_is_served(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"].startswith("Agent Governance")
