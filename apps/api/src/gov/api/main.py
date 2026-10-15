"""Control-plane application factory.

Composition happens here and nowhere else: the factory wires transport-level
concerns (error contract, health, telemetry) and leaves business behaviour to
the application and domain layers.
"""

from __future__ import annotations

from fastapi import FastAPI

from gov.api.application.approval.service import ApprovalService
from gov.api.application.audit.denials import DenialRecorder
from gov.api.application.audit.queries import AuditQueryService
from gov.api.application.permission.assignments import AssignmentService
from gov.api.application.permission.responsibility import ResponsibilityService
from gov.api.application.permission.roles import RoleService
from gov.api.application.permission.users import UserService
from gov.api.application.registry.service import RegistryService
from gov.api.infrastructure.redaction import DEFAULT_REDACTOR
from gov.api.interface.approval.router import router as approval_router
from gov.api.interface.audit.router import router as audit_router
from gov.api.interface.errors import register_problem_handlers
from gov.api.interface.permission.assignments import router as assignment_router
from gov.api.interface.permission.responsibility import router as responsibility_router
from gov.api.interface.permission.roles import router as role_router
from gov.api.interface.permission.users import router as user_router
from gov.api.interface.registry.router import router as registry_router


def create_app(
    *,
    approval_service: ApprovalService | None = None,
    registry_service: RegistryService | None = None,
    user_service: UserService | None = None,
    role_service: RoleService | None = None,
    assignment_service: AssignmentService | None = None,
    responsibility_service: ResponsibilityService | None = None,
    audit_service: AuditQueryService | None = None,
    denial_recorder: DenialRecorder | None = None,
) -> FastAPI:
    """Build and configure the control-plane application.

    The services are supplied by the composition root once the persistence
    adapter exists. Without one, its endpoints still exist and refuse with 503,
    which is preferable to routes that silently vanish.
    """
    app = FastAPI(
        title="Agent Governance and Control Platform API",
        version="0.1.0",
        description=(
            "Control plane for Agent, Tool and Model governance. All endpoints "
            "are organisation-scoped: the organisation is taken from the bearer "
            "token, never from a request parameter."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    # The app factory is the composition root: it is the one place that may join
    # the interface layer to an infrastructure adapter.
    register_problem_handlers(
        app, redactor=DEFAULT_REDACTOR.redact, denial_recorder=denial_recorder
    )
    app.include_router(approval_router)
    app.include_router(registry_router)
    app.include_router(user_router)
    app.include_router(role_router)
    app.include_router(assignment_router)
    app.include_router(responsibility_router)
    app.include_router(audit_router)
    app.state.approval_service = approval_service
    app.state.registry_service = registry_service
    app.state.user_service = user_service
    app.state.role_service = role_service
    app.state.assignment_service = assignment_service
    app.state.responsibility_service = responsibility_service
    app.state.audit_service = audit_service
    app.state.denial_recorder = denial_recorder

    @app.get("/healthz", tags=["Operations"], summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
