"""Create the Tool Registry tables: tool and tool_permission.

Revision ID: 0004_tool_registry
Revises: 0003_registry
Create Date: 2026-10-14

T038 named all four registry tables in one revision. They are split here because
the Agent Registry and the Tool Registry are separate governance domains with
separate lifecycles: one revision per registry keeps review, rollback and blame
honest. This revision completes the remainder of T038.

Not stored: `requires_sandbox_class` is a pure function of `risk_level` (ADR-0006),
so it is derived rather than persisted. A stored copy could drift from the risk
level that produced it, and the domain already exposes it as a property.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_tool_registry"
down_revision: str | None = "0003_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "gov_app"
TENANT_SETTING = "app.organisation_id"

REGISTRY_TABLES: tuple[str, ...] = ("tool", "tool_permission")


def _tenant_predicate() -> str:
    """Fail-closed tenant predicate; see 0003_registry for the reasoning."""
    return (
        f"organisation_id = nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"
    )


def upgrade() -> None:
    op.execute(
        "CREATE TYPE tool_risk_level AS ENUM ('low', 'medium', 'high', 'critical')"
    )
    op.execute(
        "CREATE TYPE tool_status AS ENUM ('draft', 'active', 'deprecated', 'retired')"
    )
    op.execute(
        "CREATE TYPE tool_action AS ENUM "
        "('read', 'write', 'execute', 'approve', 'delete')"
    )
    op.execute(
        "CREATE TYPE data_class AS ENUM "
        "('public', 'internal', 'confidential', 'restricted')"
    )

    # ------------------------------------------------------------------- tool

    op.create_table(
        "tool",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column(
            "risk_level",
            postgresql.ENUM(name="tool_risk_level", create_type=False),
            nullable=False,
        ),
        # A risk level without a stated basis is an assertion, not a judgement.
        sa.Column("risk_basis", sa.String(length=2000), nullable=False),
        sa.Column("adapter_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="tool_status", create_type=False),
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
        sa.PrimaryKeyConstraint("id", name="tool_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="tool_organisation_fk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organisation_id", "name", name="tool_organisation_name_uq"),
        # Target for the composite foreign key from tool_permission.
        sa.UniqueConstraint("organisation_id", "id", name="tool_organisation_id_uq"),
        sa.CheckConstraint("btrim(name) <> ''", name="tool_name_not_blank"),
        sa.CheckConstraint("btrim(risk_basis) <> ''", name="tool_risk_basis_not_blank"),
        sa.CheckConstraint("btrim(adapter_ref) <> ''", name="tool_adapter_ref_not_blank"),
        sa.CheckConstraint(
            "char_length(description) <= 4000", name="tool_description_length"
        ),
    )

    # -------------------------------------------------------- tool_permission

    op.create_table(
        "tool_permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=200), nullable=False),
        sa.Column(
            "action",
            postgresql.ENUM(name="tool_action", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "data_class",
            postgresql.ENUM(name="data_class", create_type=False),
            nullable=False,
        ),
        # Optional narrowing (row filters, limits). Named `narrowing` rather than
        # the data model's `constraint`, which is a reserved word in PostgreSQL
        # and would need quoting at every use.
        sa.Column(
            "narrowing",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id", name="tool_permission_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="tool_permission_organisation_fk",
            ondelete="RESTRICT",
        ),
        # Composite: a permission cannot be attached to a Tool in another
        # organisation, even if a policy were misconfigured.
        sa.ForeignKeyConstraint(
            ["organisation_id", "tool_id"],
            ["tool.organisation_id", "tool.id"],
            name="tool_permission_tool_fk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tool_id",
            "resource_type",
            "action",
            "data_class",
            name="tool_permission_uq",
        ),
        sa.CheckConstraint(
            "btrim(resource_type) <> ''", name="tool_permission_resource_not_blank"
        ),
    )

    # ------------------------------------------------------------------ indexes

    op.create_index("tool_status_idx", "tool", ["organisation_id", "status"])
    # The high-risk inventory the Approval Center and dashboard read; partial
    # because high and critical tools are the minority and the query always names
    # those two levels.
    op.create_index(
        "tool_high_risk_idx",
        "tool",
        ["organisation_id"],
        postgresql_where=sa.text("risk_level IN ('high', 'critical')"),
    )
    # Every permission of a Tool: the detail screen's query, and what the gateway
    # reads when it validates parameters against a Tool's declared surface.
    op.create_index(
        "tool_permission_tool_idx", "tool_permission", ["organisation_id", "tool_id"]
    )

    # ------------------------------------------------------- multi-tenancy

    predicate = _tenant_predicate()
    for table in REGISTRY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
        # A Tool is deprecated or retired, never deleted: audit events point at
        # it, and a dangling target makes a trail unexplainable.
        op.execute(f"REVOKE DELETE ON {table} FROM {APPLICATION_ROLE}")


def downgrade() -> None:
    """Drop the Tool Registry schema. Local resets only; see ADR-0010."""
    for table in REGISTRY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_index("tool_permission_tool_idx", table_name="tool_permission")
    op.drop_table("tool_permission")

    op.drop_index("tool_high_risk_idx", table_name="tool")
    op.drop_index("tool_status_idx", table_name="tool")
    op.drop_table("tool")

    for type_name in ("data_class", "tool_action", "tool_status", "tool_risk_level"):
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
