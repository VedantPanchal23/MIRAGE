"""Add Gate 3 Action Assurance, Tool Registry, and Action Approvals with RLS.

Revision ID: 007_gate3_action_and_tool_governance
Revises: 006_gate2_context_and_memory
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "007_gate3_action_governance"
down_revision: str | None = "006_gate2_context_and_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_rls(table: str) -> None:
    """Attach a fail-closed tenant RLS policy to a table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL "
        "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))"
    )


def upgrade() -> None:
    # 1. Create tool_registry table
    op.create_table(
        "tool_registry",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_type", sa.String(32), nullable=False, server_default="NATIVE"),
        sa.Column("egress_type", sa.String(32), nullable=False, server_default="INTERNAL_ISOLATED"),
        sa.Column("trust_level", sa.String(32), nullable=False, server_default="VERIFIED"),
        sa.Column("required_capability", sa.String(128), nullable=False),
        sa.Column("parameters_schema", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tool_registry_tenant_name"),
    )
    op.create_index("ix_tool_registry_tenant_id", "tool_registry", ["tenant_id"])

    # 2. Create action_contracts table
    op.create_table(
        "action_contracts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_identity_id",
            sa.String(64),
            sa.ForeignKey("actor_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "tool_id",
            sa.String(64),
            sa.ForeignKey("tool_registry.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False, server_default="EXECUTE"),
        sa.Column("target_resource", sa.String(512), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("normalized_parameters", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parameters_hash", sa.String(64), nullable=False),
        sa.Column("required_capability", sa.String(128), nullable=False),
        sa.Column("taint_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blast_radius", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state", sa.String(32), nullable=False, server_default="PROPOSED"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("preconditions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("postconditions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("observed_result", JSONB(), nullable=True),
        sa.Column("approval_id", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_contracts_tenant_idempotency"),
    )
    op.create_index("ix_action_contracts_tenant_id", "action_contracts", ["tenant_id"])
    op.create_index("ix_action_contracts_transaction_id", "action_contracts", ["transaction_id"])
    op.create_index("ix_action_contracts_actor_identity_id", "action_contracts", ["actor_identity_id"])
    op.create_index("ix_action_contracts_tool_id", "action_contracts", ["tool_id"])
    op.create_index("ix_action_contracts_state", "action_contracts", ["state"])

    # 3. Create action_approvals table
    op.create_table(
        "action_approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("action_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("required_role", sa.String(32), nullable=False, server_default="SUPER_ADMIN"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("parameters_hash", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_action_approvals_tenant_id", "action_approvals", ["tenant_id"])
    op.create_index("ix_action_approvals_action_id", "action_approvals", ["action_id"])
    op.create_index("ix_action_approvals_transaction_id", "action_approvals", ["transaction_id"])
    op.create_index("ix_action_approvals_status", "action_approvals", ["status"])

    # 4. Enforce PostgreSQL Row-Level Security on all three tables
    _tenant_rls("tool_registry")
    _tenant_rls("action_contracts")
    _tenant_rls("action_approvals")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_action_approvals ON action_approvals")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_action_contracts ON action_contracts")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_tool_registry ON tool_registry")
    op.drop_table("action_approvals")
    op.drop_table("action_contracts")
    op.drop_table("tool_registry")
