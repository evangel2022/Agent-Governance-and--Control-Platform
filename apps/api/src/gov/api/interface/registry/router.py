"""Agent Registry endpoints (FR-005 to FR-010, US1).

Authorisation follows the implemented permission matrix, which is the authority
where the task list and the matrix disagree: registering and updating need
`registry.write`, held by the administrator and the Agent Developer, while
retiring needs `registry.retire`, held only by the administrator.

`PATCH` may change the description, the owner, or move the Agent to `retired`.
Other lifecycle states are reached through the workflow that produces them -
releasing a version is what makes an Agent active - so this endpoint refuses
them rather than silently ignoring the field.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, Query, Request

from gov.api.application.ports import ApplicationError
from gov.api.application.registry.service import RegistryService
from gov.api.domain.identity.permissions import (
    REGISTRY_READ,
    REGISTRY_RETIRE,
    REGISTRY_WRITE,
)
from gov.api.domain.registry.entities import DomainValidationError
from gov.api.interface.errors import ValidationProblem, translate_application_error
from gov.api.interface.pagination import InvalidPageToken, paginate
from gov.api.interface.registry.schemas import (
    AgentCreate,
    AgentOut,
    AgentPage,
    AgentUpdate,
    AgentVersionCreate,
    AgentVersionOut,
)
from gov.api.interface.security.authorize import (
    require_effective_permission_from_state,
)
from gov.api.interface.security.dependencies import get_principal, service_dependency
from gov.api.interface.security.oidc import Principal

router = APIRouter(prefix="/v1/agents", tags=["Registry"])

#: Resolved from the application state; supplied by the composition root.
get_registry_service = service_dependency("registry_service", "registry")


def _fail(error: Exception) -> NoReturn:
    """Turn a refusal into the problem response the contract promises."""
    if isinstance(error, DomainValidationError):
        raise ValidationProblem(
            str(error),
            errors=[{"field": error.field, "message": error.message}],
        ) from error
    if isinstance(error, ApplicationError):
        raise translate_application_error(error) from error
    raise error


def _agent_resource(request: Request) -> Mapping[str, Any] | None:
    """Describe the Agent a single-resource write is about, for the decision.

    The decision component needs the accountable person to apply the
    accountability rule, and this is the only place that knows which Agent the
    request names. An Agent that cannot be read yields no resource, which the
    rule treats as a refusal rather than as an unscoped action.
    """
    agent_id = request.path_params.get("agent_id")
    service = getattr(request.app.state, "registry_service", None)
    principal = getattr(request.state, "principal", None)
    if not agent_id or service is None or principal is None:
        return None
    try:
        agent = service.get_agent(
            organisation_id=principal.organisation_id, agent_id=agent_id
        )
    except Exception:
        return None
    return {
        "type": "agent",
        "id": agent.id,
        "owner_user_id": agent.owner_user_id,
    }


@router.get(
    "",
    dependencies=[Depends(require_effective_permission_from_state(REGISTRY_READ))],
)
async def list_agents(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    owner_user_id: Annotated[str | None, Query()] = None,
    page_size: Annotated[int | None, Query(ge=1, le=200)] = None,
    page_token: Annotated[str | None, Query()] = None,
) -> AgentPage:
    """List Agents in the caller's organisation."""
    records = service.list_agents(
        organisation_id=principal.organisation_id,
        status=status_filter,
        owner_user_id=owner_user_id,
    )
    try:
        page = paginate(records, page_size, page_token)
    except InvalidPageToken as error:
        raise ValidationProblem(str(error)) from error
    return AgentPage(
        items=[AgentOut.from_record(record) for record in page.items],
        total=page.total,
        next_page_token=page.next_page_token,
    )


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(require_effective_permission_from_state(REGISTRY_WRITE))],
)
async def create_agent(
    body: AgentCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentOut:
    """Register an Agent."""
    try:
        record = service.create_agent(
            organisation_id=principal.organisation_id,
            name=body.name,
            owner_user_id=body.owner_user_id,
            actor=principal.user_id,
            description=body.description,
        )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return AgentOut.from_record(record)


@router.get(
    "/{agent_id}",
    dependencies=[Depends(require_effective_permission_from_state(REGISTRY_READ))],
)
async def get_agent(
    agent_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentOut:
    """Return one Agent."""
    try:
        record = service.get_agent(
            organisation_id=principal.organisation_id, agent_id=agent_id
        )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return AgentOut.from_record(record)


@router.patch(
    "/{agent_id}",
    dependencies=[
        Depends(
            require_effective_permission_from_state(
                REGISTRY_WRITE,
                resource=_agent_resource,
                requires_resource_accountability=True,
            )
        )
    ],
)
async def update_agent(
    request: Request,
    agent_id: str,
    body: AgentUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentOut:
    """Update an Agent, or retire it."""
    if body.status is not None and body.status != "retired":
        raise ValidationProblem(
            "only 'retired' may be set through this endpoint",
            errors=[
                {
                    "field": "status",
                    "message": "releasing a version is what activates an agent",
                }
            ],
        )

    try:
        if body.status == "retired":
            # Retiring is a distinct authority from writing, so it is checked
            # separately rather than folded into the route's guard.
            await require_effective_permission_from_state(REGISTRY_RETIRE)(request)
            record = service.retire_agent(
                organisation_id=principal.organisation_id,
                agent_id=agent_id,
                actor=principal.user_id,
            )
        else:
            record = service.update_agent(
                organisation_id=principal.organisation_id,
                agent_id=agent_id,
                actor=principal.user_id,
                description=body.description,
                owner_user_id=body.owner_user_id,
            )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return AgentOut.from_record(record)


@router.get(
    "/{agent_id}/versions",
    dependencies=[Depends(require_effective_permission_from_state(REGISTRY_READ))],
)
async def list_versions(
    agent_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> list[AgentVersionOut]:
    """List an Agent's versions."""
    try:
        records = service.list_versions(
            organisation_id=principal.organisation_id, agent_id=agent_id
        )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return [AgentVersionOut.from_record(record) for record in records]


@router.post(
    "/{agent_id}/versions",
    status_code=201,
    dependencies=[
        Depends(
            require_effective_permission_from_state(
                REGISTRY_WRITE,
                resource=_agent_resource,
                requires_resource_accountability=True,
            )
        )
    ],
)
async def add_version(
    agent_id: str,
    body: AgentVersionCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentVersionOut:
    """Add a version to an Agent."""
    try:
        record = service.add_version(
            organisation_id=principal.organisation_id,
            agent_id=agent_id,
            version=body.version,
            owner_user_id=body.owner_user_id,
            actor=principal.user_id,
            model_id=body.model_id,
        )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return AgentVersionOut.from_record(record)


@router.post(
    "/{agent_id}/versions/{version}/release",
    dependencies=[
        Depends(
            require_effective_permission_from_state(
                REGISTRY_WRITE,
                resource=_agent_resource,
                requires_resource_accountability=True,
            )
        )
    ],
)
async def release_version(
    agent_id: str,
    version: str,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentVersionOut:
    """Release a version, demoting the previously released one (FR-006)."""
    try:
        record = service.release_version(
            organisation_id=principal.organisation_id,
            agent_id=agent_id,
            version=version,
            actor=principal.user_id,
        )
    except (ApplicationError, DomainValidationError) as error:
        _fail(error)
    return AgentVersionOut.from_record(record)
