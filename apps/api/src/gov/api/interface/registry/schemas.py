"""Request and response schemas for the Agent Registry.

These mirror `contracts/openapi.yaml`. Response schemas are built from the
application records rather than from the domain entities, because the contract
carries persistence timestamps the domain does not model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from gov.api.application.ports import AgentRecord, AgentVersionRecord

NAME_MAX = 200
DESCRIPTION_MAX = 4000
VERSION_MAX = 64


class AgentCreate(BaseModel):
    """Registration payload for a new Agent."""

    name: str = Field(min_length=1, max_length=NAME_MAX)
    owner_user_id: str = Field(min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)


class AgentUpdate(BaseModel):
    """Mutable attributes of an existing Agent."""

    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    owner_user_id: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    status: str | None = Field(default=None, max_length=32)


class AgentVersionCreate(BaseModel):
    """A new version of an Agent."""

    version: str = Field(min_length=1, max_length=VERSION_MAX)
    owner_user_id: str = Field(min_length=1, max_length=NAME_MAX)
    model_id: str | None = None


class AgentOut(BaseModel):
    """An Agent as the API presents it."""

    id: str
    name: str
    description: str | None
    owner_user_id: str
    status: str
    active_version_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: AgentRecord) -> AgentOut:
        return cls(
            id=record.id,
            name=record.name,
            description=record.description,
            owner_user_id=record.owner_user_id,
            status=record.status,
            active_version_id=record.active_version_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class AgentVersionOut(BaseModel):
    """A version of an Agent as the API presents it."""

    id: str
    agent_id: str
    version: str
    owner_user_id: str
    status: str
    model_id: str | None
    released_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: AgentVersionRecord) -> AgentVersionOut:
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            version=record.version,
            owner_user_id=record.owner_user_id,
            status=record.status,
            model_id=record.model_id,
            released_at=record.released_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class AgentPage(BaseModel):
    """One page of Agents."""

    items: list[AgentOut]
    total: int
    next_page_token: str | None = None
