"""Create the Agent Registry tables: agent and agent_version.

Revision ID: 0003_registry
Revises: 0002_audit_event
Create Date: 2026-10-14

Scope: the Agent Registry only (FR-005, FR-006, FR-009, FR-010). Task T038 also
names `tool` and `tool_permission`; those belong to the Tool Registry and are
deliberately not created here, so that each registry owns one revision. See the
design note at the end of this module.

Depends on:
  * `0001_identity` (T018) for `organisation` and `user`. Not yet written, so the
    chain is currently dangling - this revision cannot be applied until it lands.
  * `0002_audit_event` for the audit trail. Registry changes are audited by
    writing `audit_event` rows in the same transaction as the change (ADR-0007),
    not by database triggers, so no schema hook is required here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_registry"
down_revision: str | None = "0002_audit_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The role the control plane connects as. It may read and write registry rows,
#: but it can never delete one: retirement is a status change, which is what keeps
#: the audit trail explainable.
APPLICATION_ROLE = "gov_app"

#: Session setting the row-level-security policies read. Bound per transaction by
#: the tenant middleware; unset means no rows are visible (fail closed).
TENANT_SETTING = "app.organisation_id"

#: Semantic version shape, matching the domain validator so the database and the
#: domain agree rather than drifting apart.
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?(\+[A-Za-z0-9.]+)?$"

REGISTRY_TABLES: tuple[str, ...] = ("agent", "agent_version")


def _tenant_predicate() -> str:
    """Row-level-security predicate, evaluated per row.

    `nullif(..., '')` guards the cast: an unset or empty setting yields NULL, the
    comparison is not true, and no row is visible. That is deliberately
    fail-closed - a missing tenant context hides data rather than exposing it.
    """
    return (
        f"organisation_id = nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"
    )


def upgrade() -> None:
    op.execute(
        "CREATE TYPE agent_status AS ENUM "
        "('draft', 'active', 'deprecated', 'retired')"
    )
    op.execute(
        "CREATE TYPE agent_version_status AS ENUM "
        "('draft', 'in_review', 'released', 'deprecated', 'retired')"
    )

    # ------------------------------------------------------------------ agent

    op.create_table(
        "agent",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_status", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="agent_pkey"),
        # RESTRICT on both parents: an organisation or owner that still owns
        # registry rows cannot be removed, which protects the audit trail from
        # losing the subject it describes.
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="agent_organisation_fk",
            ondelete="RESTRICT",
        ),
        # Composite, like the agent foreign key below: an Agent cannot be owned by
        # a user in another organisation.
        sa.ForeignKeyConstraint(
            ["organisation_id", "owner_user_id"],
            ["user.organisation_id", "user.id"],
            name="agent_owner_fk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organisation_id", "name", name="agent_organisation_name_uq"),
        # Target for the composite foreign key below. Redundant with the primary
        # key on its own, but PostgreSQL requires a unique constraint on exactly
        # the referenced column set, and this is what lets a child row be
        # prevented from naming a parent in another organisation.
        sa.UniqueConstraint("organisation_id", "id", name="agent_organisation_id_uq"),
        sa.CheckConstraint("btrim(name) <> ''", name="agent_name_not_blank"),
        sa.CheckConstraint(
            "char_length(description) <= 4000", name="agent_description_length"
        ),
    )

    # ---------------------------------------------------------- agent_version

    op.create_table(
        "agent_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_version_status", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        # The model table is created by the Model Registry revision, which lands
        # after this one, so no foreign key is declared here. Add it in that
        # revision, once the target exists; declaring it now would make this
        # migration unapplicable.
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="agent_version_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="agent_version_organisation_fk",
            ondelete="RESTRICT",
        ),
        # Composite key: a version must belong to an Agent *in the same
        # organisation*. Row-level security scopes reads, but this makes a
        # cross-tenant reference impossible to store in the first place, which is
        # the difference between defence in depth and a single control.
        sa.ForeignKeyConstraint(
            ["organisation_id", "agent_id"],
            ["agent.organisation_id", "agent.id"],
            name="agent_version_agent_fk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "owner_user_id"],
            ["user.organisation_id", "user.id"],
            name="agent_version_owner_fk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("agent_id", "version", name="agent_version_uq"),
        sa.CheckConstraint(
            f"version ~ '{SEMVER_PATTERN}'", name="agent_version_semver"
        ),
        sa.CheckConstraint(
            "status <> 'released' OR released_at IS NOT NULL",
            name="agent_version_released_at_required",
        ),
    )

    # ------------------------------------------------------------------ indexes

    # Listing an organisation's Agents by lifecycle state, which is the registry
    # screen's default filter.
    op.create_index("agent_status_idx", "agent", ["organisation_id", "status"])
    # "Agents owned by me", and the accountability report.
    op.create_index("agent_owner_idx", "agent", ["organisation_id", "owner_user_id"])
    # Version history for one Agent: the detail screen's query.
    op.create_index(
        "agent_version_agent_idx", "agent_version", ["organisation_id", "agent_id"]
    )
    # "Every released version in this organisation", used by the release and
    # dashboard views.
    op.create_index(
        "agent_version_status_idx", "agent_version", ["organisation_id", "status"]
    )
    # Which versions depend on a given model (FR-008), filtered because most rows
    # have no model once the Model Registry arrives.
    op.create_index(
        "agent_version_model_idx",
        "agent_version",
        ["organisation_id", "model_id"],
        postgresql_where=sa.text("model_id IS NOT NULL"),
    )
    # FR-006: at most one released version per Agent, enforced by the database so
    # concurrent releases cannot both win.
    op.create_index(
        "agent_version_active_uq",
        "agent_version",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'released'"),
    )

    # ------------------------------------------------------- multi-tenancy

    predicate = _tenant_predicate()
    for table in REGISTRY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE applies the policy to the table owner too, so a misconfigured
        # connection cannot read across tenants by accident.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}"
        )
        # No DELETE grant: registry rows are retired, never removed, so the audit
        # trail always has a subject to point at.
        op.execute(f"REVOKE DELETE ON {table} FROM {APPLICATION_ROLE}")


def downgrade() -> None:
    """Drop the Agent Registry schema.

    Migrations are forward-only in this project (ADR-0010). This exists so a
    development environment can be reset, and is never run against a deployment
    holding registry or audit history.
    """
    for table in REGISTRY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_index("agent_version_active_uq", table_name="agent_version")
    op.drop_index("agent_version_model_idx", table_name="agent_version")
    op.drop_index("agent_version_status_idx", table_name="agent_version")
    op.drop_index("agent_version_agent_idx", table_name="agent_version")
    op.drop_index("agent_owner_idx", table_name="agent")
    op.drop_index("agent_status_idx", table_name="agent")

    op.drop_table("agent_version")
    op.drop_table("agent")

    sa.Enum(name="agent_version_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="agent_status").drop(op.get_bind(), checkfirst=True)
