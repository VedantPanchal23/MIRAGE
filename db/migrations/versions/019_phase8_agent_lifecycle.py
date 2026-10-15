"""Phase 8: Agent lifecycle governance, explicit states, and registration metadata.

Revision ID: 019_phase8_agent_lifecycle
Revises: 018_phase8_cross_agent_gov
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019_phase8_agent_lifecycle"
down_revision: str | None = "018_phase8_cross_agent_gov"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add agent lifecycle and provenance columns to agents table
    op.add_column(
        "agents",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "agents",
        sa.Column(
            "registered_by_identity_id",
            sa.String(64),
            sa.ForeignKey("actor_identities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("suspension_reason", sa.String(512), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("revocation_reason", sa.String(512), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 2. Add composite index for tenant-scoped lifecycle queries
    op.create_index(
        "ix_agents_tenant_status",
        "agents",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agents_tenant_status", table_name="agents")
    op.drop_column("agents", "updated_at")
    op.drop_column("agents", "revocation_reason")
    op.drop_column("agents", "suspension_reason")
    op.drop_column("agents", "revoked_at")
    op.drop_column("agents", "suspended_at")
    op.drop_column("agents", "registered_by_identity_id")
    op.drop_column("agents", "status")
