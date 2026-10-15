"""Create the identity baseline: organisation, user, role, role_assignment.

Revision ID: 0001_identity
Revises: None
Create Date: 2026-10-14

This is the root of the migration chain and the tenancy anchor: every
tenant-scoped table in the platform references `organisation`, and row-level
security everywhere reads the session setting established here.

It also creates the application role that later revisions grant privileges to.
That would normally belong with the least-privilege grant work (T019), but
`0002_audit_event` and `0003_registry` already issue `GRANT` statements, and a
GRANT to a role that does not exist fails. Creating it here, idempotently, is
what makes those revisions applicable in order.

Reference data: the five built-in roles are inserted here, as `data-model.md`
specifies, with fixed identifiers so every deployment has the same well-known
values. The seed command (T034) covers demo organisation and demo accounts, not
these.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "gov_app"
TENANT_SETTING = "app.organisation_id"

#: Well-known identifiers for the built-in roles, so a deployment can reference
#: them without a lookup and a re-run is idempotent.
BUILT_IN_ROLES: tuple[tuple[str, str, str, str], ...] = (
    (
        "00000000-0000-0000-0000-000000000001",
        "platform_administrator",
        "Platform Administrator",
        "Registers Agents, Tools and Models; operates the platform",
    ),
    (
        "00000000-0000-0000-0000-000000000002",
        "agent_developer",
        "Agent Developer",
        "Registers and releases Agent versions",
    ),
    (
        "00000000-0000-0000-0000-000000000003",
        "security_compliance",
        "Security and Compliance",
        "Authors policies and oversees compliance",
    ),
    (
        "00000000-0000-0000-0000-000000000004",
        "business_approver",
        "Business Approver",
        "Approves or rejects high-risk operations",
    ),
    (
        "00000000-0000-0000-0000-000000000005",
        "auditor",
        "Auditor",
        "Searches and exports the audit trail",
    ),
)


def _tenant_predicate() -> str:
    """Fail-closed tenant predicate; see 0003_registry for the reasoning."""
    return (
        f"organisation_id = nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"
    )


def _create_application_role() -> None:
    """Create the application role if it is absent.

    Idempotent, and deliberately without privileges: grants are issued table by
    table so that a new table is not silently world-readable.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                CREATE ROLE {APPLICATION_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_application_role()

    op.execute(
        "CREATE TYPE organisation_status AS ENUM ('active', 'suspended', 'closed')"
    )
    op.execute("CREATE TYPE user_status AS ENUM ('active', 'disabled')")
    op.execute(
        "CREATE TYPE role_code AS ENUM "
        "('platform_administrator', 'agent_developer', 'security_compliance', "
        "'business_approver', 'auditor')"
    )
    op.execute(
        "CREATE TYPE assignment_scope_type AS ENUM ('organisation', 'agent', 'tool')"
    )

    # ----------------------------------------------------------- organisation

    op.create_table(
        "organisation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="organisation_status", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("residency_region", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="organisation_pkey"),
        sa.UniqueConstraint("name", name="organisation_name_uq"),
        sa.CheckConstraint("btrim(name) <> ''", name="organisation_name_not_blank"),
    )

    # ------------------------------------------------------------------- user

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="user_status", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="user_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="user_organisation_fk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organisation_id", "external_subject", name="user_external_subject_uq"
        ),
        # Referenced by the composite foreign keys that keep child rows inside
        # their own organisation (see 0003_registry).
        sa.UniqueConstraint("organisation_id", "id", name="user_organisation_id_uq"),
        sa.CheckConstraint("btrim(display_name) <> ''", name="user_display_name_not_blank"),
        sa.CheckConstraint("btrim(email) <> ''", name="user_email_not_blank"),
    )
    op.create_index("user_organisation_status_idx", "user", ["organisation_id", "status"])

    # ------------------------------------------------------------------- role

    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL for the built-in roles, which every organisation shares.
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "code", postgresql.ENUM(name="role_code", create_type=False), nullable=False
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="role_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="role_organisation_fk",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("btrim(name) <> ''", name="role_name_not_blank"),
    )
    # Two partial uniques: one code per organisation for custom roles, and one row
    # per code for the built-ins, whose organisation is NULL.
    op.create_index(
        "role_builtin_code_uq",
        "role",
        ["code"],
        unique=True,
        postgresql_where=sa.text("organisation_id IS NULL"),
    )
    op.create_index(
        "role_organisation_code_uq",
        "role",
        ["organisation_id", "code"],
        unique=True,
        postgresql_where=sa.text("organisation_id IS NOT NULL"),
    )

    # -------------------------------------------------------- role_assignment

    op.create_table(
        "role_assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scope_type",
            postgresql.ENUM(name="assignment_scope_type", create_type=False),
            nullable=False,
            server_default=sa.text("'organisation'"),
        ),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Least privilege: a grant may be time-bound even when the role is not.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="role_assignment_pkey"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name="role_assignment_organisation_fk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "user_id"],
            ["user.organisation_id", "user.id"],
            name="role_assignment_user_fk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="role_assignment_role_fk", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            name="role_assignment_granted_by_fk",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(scope_type = 'organisation' AND scope_id IS NULL) "
            "OR (scope_type <> 'organisation' AND scope_id IS NOT NULL)",
            name="role_assignment_scope_consistent",
        ),
    )
    # NULLS NOT DISTINCT so an organisation-scoped grant (scope_id NULL) cannot be
    # duplicated: with the default NULL handling, every duplicate would look
    # distinct and the constraint would enforce nothing.
    op.execute(
        "CREATE UNIQUE INDEX role_assignment_uq ON role_assignment "
        "(organisation_id, user_id, role_id, scope_type, scope_id) NULLS NOT DISTINCT"
    )
    op.create_index(
        "role_assignment_user_idx", "role_assignment", ["organisation_id", "user_id"]
    )
    # Drives the expiry sweep that revokes lapsed grants.
    op.create_index(
        "role_assignment_expiry_idx",
        "role_assignment",
        ["organisation_id", "expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )

    # ----------------------------------------------------- multi-tenancy

    predicate = _tenant_predicate()
    for table in ("user", "role_assignment"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )

    # The built-in roles have no organisation and must remain visible to every
    # tenant; custom roles are scoped like everything else.
    op.execute("ALTER TABLE role ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY role_tenant_isolation ON role "
        f"USING (organisation_id IS NULL OR {predicate}) "
        f"WITH CHECK (organisation_id IS NULL OR {predicate})"
    )

    # `organisation` is the tenancy root and is not itself tenant-filtered; access
    # is constrained by the identity provider rather than by a policy.
    for table in ("organisation", "user", "role", "role_assignment"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
        # Revocation and retirement are UPDATEs (clear `expires_at`, set `status`),
        # so identity history survives alongside the audit trail.
        op.execute(f"REVOKE DELETE ON {table} FROM {APPLICATION_ROLE}")

    # ------------------------------------------------------- reference data

    values = ", ".join(
        f"('{role_id}'::uuid, NULL, '{code}'::role_code, '{name}', '{description}')"
        for role_id, code, name, description in BUILT_IN_ROLES
    )
    op.execute(
        "INSERT INTO role (id, organisation_id, code, name, description) "
        f"VALUES {values} ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Drop the identity baseline. Local resets only; see ADR-0010."""
    op.execute("DROP POLICY IF EXISTS role_tenant_isolation ON role")
    for table in ("user", "role_assignment"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_index("role_assignment_expiry_idx", table_name="role_assignment")
    op.drop_index("role_assignment_user_idx", table_name="role_assignment")
    op.execute("DROP INDEX IF EXISTS role_assignment_uq")
    op.drop_table("role_assignment")

    op.drop_index("role_organisation_code_uq", table_name="role")
    op.drop_index("role_builtin_code_uq", table_name="role")
    op.drop_table("role")

    op.drop_index("user_organisation_status_idx", table_name="user")
    op.drop_table("user")
    op.drop_table("organisation")

    for type_name in (
        "assignment_scope_type",
        "role_code",
        "user_status",
        "organisation_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
