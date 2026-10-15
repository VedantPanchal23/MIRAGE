"""Phase 8: Governed Agent Handoffs, Resource Leases, and Fencing Tokens.

Revision ID: 020_phase8_handoff_concurrency
Revises: 019_phase8_agent_lifecycle
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "020_phase8_handoff_concurrency"
down_revision: str | None = "019_phase8_agent_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Add fencing_token to action_contracts for execution-boundary verification
    op.add_column(
        "action_contracts",
        sa.Column("fencing_token", sa.BigInteger(), nullable=True),
    )

    # 2. Create agent_handoffs table
    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
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
            "parent_agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
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
            "delegation_id",
            sa.String(64),
            sa.ForeignKey("agent_delegations.id", ondelete="RESTRICT"),
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
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column(
            "permitted_scope",
            JSONB() if is_postgres else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb" if is_postgres else "'{}'"),
        ),
        sa.Column(
            "inherited_taint_flags",
            JSONB() if is_postgres else sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"),
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(512), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_handoffs_tenant_idempotency"),
    )

    op.create_index(
        "ix_agent_handoffs_tenant_parent_txn",
        "agent_handoffs",
        ["tenant_id", "parent_transaction_id"],
    )
    op.create_index(
        "ix_agent_handoffs_tenant_child_agent",
        "agent_handoffs",
        ["tenant_id", "child_agent_id"],
    )
    op.create_index(
        "ix_agent_handoffs_tenant_delegation",
        "agent_handoffs",
        ["tenant_id", "delegation_id"],
    )
    op.create_index(
        "ix_agent_handoffs_tenant_status",
        "agent_handoffs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_agent_handoffs_tenant_expires",
        "agent_handoffs",
        ["tenant_id", "expires_at"],
    )

    # 3. Create resource_leases table
    op.create_table(
        "resource_leases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("resource_uri", sa.String(512), nullable=False, index=True),
        sa.Column(
            "holder_agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "holder_transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "holder_handoff_id",
            sa.String(64),
            sa.ForeignKey("agent_handoffs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("concurrency_mode", sa.String(32), nullable=False, server_default="EXCLUSIVE"),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACQUIRED"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
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
    )

    op.create_index(
        "ix_resource_leases_tenant_resource_status",
        "resource_leases",
        ["tenant_id", "resource_uri", "status"],
    )
    op.create_index(
        "ix_resource_leases_tenant_holder_txn",
        "resource_leases",
        ["tenant_id", "holder_transaction_id"],
    )
    op.create_index(
        "ix_resource_leases_tenant_expires",
        "resource_leases",
        ["tenant_id", "expires_at"],
    )

    # 4. Security Hardening: Row-Level Security and least-privilege mirage_app role grants
    if is_postgres:
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON agent_handoffs TO mirage_app;
                    GRANT SELECT, INSERT, UPDATE, DELETE ON resource_leases TO mirage_app;
                END IF;
            END
            $$;
            """
        )
        op.execute("ALTER TABLE agent_handoffs ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_handoffs FORCE ROW LEVEL SECURITY;")
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'agent_handoffs' AND policyname = 'tenant_isolation_agent_handoffs'
                ) THEN
                    CREATE POLICY tenant_isolation_agent_handoffs ON agent_handoffs FOR ALL
                    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
                END IF;
            END
            $$;
            """
        )

        op.execute("ALTER TABLE resource_leases ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE resource_leases FORCE ROW LEVEL SECURITY;")
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'resource_leases' AND policyname = 'tenant_isolation_resource_leases'
                ) THEN
                    CREATE POLICY tenant_isolation_resource_leases ON resource_leases FOR ALL
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
        op.drop_index("ix_resource_leases_tenant_expires", table_name="resource_leases")
        op.drop_index("ix_resource_leases_tenant_holder_txn", table_name="resource_leases")
        op.drop_index("ix_resource_leases_tenant_resource_status", table_name="resource_leases")
        op.drop_index("ix_agent_handoffs_tenant_expires", table_name="agent_handoffs")
        op.drop_index("ix_agent_handoffs_tenant_status", table_name="agent_handoffs")
        op.drop_index("ix_agent_handoffs_tenant_delegation", table_name="agent_handoffs")
        op.drop_index("ix_agent_handoffs_tenant_child_agent", table_name="agent_handoffs")
        op.drop_index("ix_agent_handoffs_tenant_parent_txn", table_name="agent_handoffs")

    op.drop_table("resource_leases")
    op.drop_table("agent_handoffs")
    op.drop_column("action_contracts", "fencing_token")
