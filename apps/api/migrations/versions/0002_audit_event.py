"""Create the audit_event table.

Revision ID: 0002_audit_event
Revises: 0001_identity
Create Date: 2026-10-13

Implements FR-023 and FR-024: every governed action produces an append-only,
tamper-evident audit event. `sequence`, `prev_hash` and `entry_hash` carry the
hash chain verified by `gov.api.domain.audit.chain` and recomputed by the
verifier job (T099).

Ordering note: this revision sits between identity and registry because the
policy/invocation migration (T048) creates indexes on `audit_event`, so the table
must already exist. The registry migration becomes 0003 and chains after this
one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_audit_event"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The role the control plane connects as. It may insert and read audit events
#: but must never mutate or remove them (see T019).
APPLICATION_ROLE = "gov_app"


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisation.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum("user", "agent", "system", name="audit_actor_type"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("success", "denied", "failure", "pending", name="audit_outcome"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("entry_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("organisation_id", "sequence", name="audit_org_seq_uq"),
        sa.CheckConstraint(
            "outcome = 'success' OR reason IS NOT NULL",
            name="audit_non_success_requires_reason",
        ),
    )

    op.create_index(
        "audit_org_time_idx",
        "audit_event",
        ["organisation_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "audit_actor_idx",
        "audit_event",
        ["organisation_id", "actor_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "audit_target_idx",
        "audit_event",
        ["organisation_id", "target_type", "target_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "audit_correlation_idx",
        "audit_event",
        ["organisation_id", "correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.create_index(
        "audit_detail_gin",
        "audit_event",
        ["detail"],
        postgresql_using="gin",
    )

    # Tenant isolation is enforced in the data layer, so a missing filter in the
    # application cannot expose another organisation's history (FR-036).
    op.execute("ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_event_tenant_isolation ON audit_event "
        "USING (organisation_id = current_setting('app.organisation_id', true)::uuid) "
        "WITH CHECK (organisation_id = current_setting('app.organisation_id', true)::uuid)"
    )

    # Append-only: corrections are new events that reference their predecessor.
    op.execute(f"GRANT SELECT, INSERT ON audit_event TO {APPLICATION_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_event FROM {APPLICATION_ROLE}")


def downgrade() -> None:
    # Forward-only migrations are the project rule (ADR-0010). This exists so the
    # development environment can be reset, and it is never run against a
    # deployment that holds audit history.
    op.execute("DROP POLICY IF EXISTS audit_event_tenant_isolation ON audit_event")
    op.drop_index("audit_detail_gin", table_name="audit_event")
    op.drop_index("audit_correlation_idx", table_name="audit_event")
    op.drop_index("audit_target_idx", table_name="audit_event")
    op.drop_index("audit_actor_idx", table_name="audit_event")
    op.drop_index("audit_org_time_idx", table_name="audit_event")
    op.drop_table("audit_event")
    sa.Enum(name="audit_outcome").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="audit_actor_type").drop(op.get_bind(), checkfirst=True)
