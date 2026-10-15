"""RFC 9457 problem-detail error contract.

Implements FR-002 (structured, typed errors at every boundary) and constitution
Principle II. Every failure that crosses the HTTP boundary returns
application/problem+json with a stable machine-readable code, so clients never
have to parse prose and no error shape differs between endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from gov.api.application.audit.denials import REFUSAL_STATUSES, DenialRecorder
from gov.api.application.ports import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailure,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"

_LOGGER = logging.getLogger(__name__)


class ApiProblem(Exception):
    """Base class for errors that map to an RFC 9457 response."""

    status: int = 500
    code: str = "internal_error"
    title: str = "Internal server error"
    type_: str = "about:blank"

    def __init__(
        self,
        detail: str,
        *,
        errors: Iterable[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors: tuple[dict[str, Any], ...] = tuple(errors or ())
        self.headers: dict[str, str] = dict(headers or {})

    def payload(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type_,
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            body["detail"] = self.detail
        if instance:
            body["instance"] = instance
        if self.errors:
            body["errors"] = [dict(item) for item in self.errors]
        return body


class UnauthorizedProblem(ApiProblem):
    status = 401
    code = "unauthorized"
    title = "Authentication required"


class ForbiddenProblem(ApiProblem):
    status = 403
    code = "forbidden"
    title = "Not permitted"


class NotFoundProblem(ApiProblem):
    status = 404
    code = "not_found"
    title = "Not found"


class ConflictProblem(ApiProblem):
    status = 409
    code = "conflict"
    title = "Conflicts with existing state"


class ValidationProblem(ApiProblem):
    status = 422
    code = "validation_error"
    title = "Request validation failed"


class ServiceUnavailableProblem(ApiProblem):
    status = 503
    code = "service_unavailable"
    title = "Service unavailable"


def translate_application_error(error: ApplicationError) -> ApiProblem:
    """Map a use-case refusal onto the problem response it deserves.

    One mapping for the whole API. Duplicating it per router is how the same
    refusal ends up as a 403 on one endpoint and a 422 on another.
    """
    if isinstance(error, NotFoundError):
        return NotFoundProblem(str(error), errors=error.errors or None)
    if isinstance(error, ForbiddenError):
        return ForbiddenProblem(str(error), errors=error.errors or None)
    if isinstance(error, ConflictError):
        return ConflictProblem(str(error), errors=error.errors or None)
    if isinstance(error, ValidationFailure):
        return ValidationProblem(str(error), errors=error.errors or None)
    return ApiProblem(str(error))


def register_problem_handlers(
    app: FastAPI,
    redactor: Callable[[Any], Any] | None = None,
    denial_recorder: DenialRecorder | None = None,
) -> None:
    """Attach the problem-detail handlers to an application.

    `redactor` is applied to every problem payload so a classified value cannot
    be echoed back to a caller (FR-040). It is injected rather than imported, so
    this layer keeps no dependency on the infrastructure layer.

    `denial_recorder`, when supplied, records every refusal that carries an
    organisation and an actor (FR-024, SC-008). It is applied here, in the one
    handler every refusal passes through, so a route cannot omit it - the
    alternative, recording in each guard, is how one route ends up silently
    unrecorded. Recording is best-effort: the refusal has already happened and
    turning a lost record into a permitted request would be the worse failure.
    """

    def clean(payload: dict[str, Any]) -> dict[str, Any]:
        if redactor is None:
            return payload
        cleaned = redactor(payload)
        return cleaned if isinstance(cleaned, dict) else payload

    @app.exception_handler(ApiProblem)
    async def _api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        _record_refusal(request, exc, denial_recorder)
        return JSONResponse(
            status_code=exc.status,
            content=clean(exc.payload(instance=str(request.url.path))),
            media_type=PROBLEM_MEDIA_TYPE,
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = []
        for item in exc.errors():
            location = [str(part) for part in item.get("loc", ())]
            errors.append(
                {
                    "field": ".".join(location[1:]) or ".".join(location),
                    "location": location,
                    "message": item.get("msg", "invalid value"),
                    "type": item.get("type", "value_error"),
                }
            )
        problem = ValidationProblem(
            "one or more fields failed validation",
            errors=errors,
        )
        return JSONResponse(
            status_code=problem.status,
            content=clean(problem.payload(instance=str(request.url.path))),
            media_type=PROBLEM_MEDIA_TYPE,
        )


def _record_refusal(
    request: Request,
    exc: ApiProblem,
    recorder: DenialRecorder | None,
) -> None:
    """Append a refusal to the trail, if it is one and can be attributed."""
    if recorder is None or exc.status not in REFUSAL_STATUSES:
        return
    principal: Any = getattr(request.state, "principal", None)
    organisation_id = getattr(principal, "organisation_id", None)
    actor = getattr(principal, "user_id", None)
    if not organisation_id or not actor:
        return
    try:
        recorder.record(
            organisation_id=organisation_id,
            actor=actor,
            status=exc.status,
            method=request.method,
            path=request.url.path,
            reason=exc.detail or exc.title,
        )
    except Exception:
        _LOGGER.exception("failed to record a refusal on %s", request.url.path)
