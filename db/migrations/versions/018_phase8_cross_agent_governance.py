"""Phase 8: Cross-Agent Delegation, authority attenuation, and multi-agent governance.

Revision ID: 018_phase8_cross_agent_gov
Revises: 017_phase7_governed_memory
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "018_phase8_cross_agent_gov"
down_revision: str | None = "017_phase7_governed_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Create agent_delegations table
    op.create_table(
        "agent_delegations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "child_agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "child_transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "delegated_capabilities",
            JSONB() if is_postgres else sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"),
        ),
        sa.Column(
            "resource_scope",
            JSONB() if is_postgres else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb" if is_postgres else "'{}'"),
        ),
        sa.Column("max_autonomy_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delegation_depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_turns", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("purpose", sa.String(500), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_delegations_tenant_idempotency"),
    )

    # 2. Performance and lookup composite indexes
    op.create_index(
        "ix_agent_delegations_tenant_parent_txn",
        "agent_delegations",
        ["tenant_id", "parent_transaction_id"],
    )
    op.create_index(
        "ix_agent_delegations_tenant_child_txn",
        "agent_delegations",
        ["tenant_id", "child_transaction_id"],
    )
    op.create_index(
        "ix_agent_delegations_tenant_status",
        "agent_delegations",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_agent_delegations_tenant_expires",
        "agent_delegations",
        ["tenant_id", "expires_at"],
    )

    # 3. Security Hardening: Row-Level Security and least-privilege mirage_app role grants
    if is_postgres:
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON agent_delegations TO mirage_app;
                END IF;
            END
            $$;
            """
        )
        op.execute("ALTER TABLE agent_delegations ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_delegations FORCE ROW LEVEL SECURITY;")
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'agent_delegations' AND policyname = 'tenant_isolation_agent_delegations'
                ) THEN
                    CREATE POLICY tenant_isolation_agent_delegations ON agent_delegations FOR ALL
                    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.drop_index("ix_agent_delegations_tenant_expires", table_name="agent_delegations")
        op.drop_index("ix_agent_delegations_tenant_status", table_name="agent_delegations")
        op.drop_index("ix_agent_delegations_tenant_child_txn", table_name="agent_delegations")
        op.drop_index("ix_agent_delegations_tenant_parent_txn", table_name="agent_delegations")

    op.drop_table("agent_delegations")
