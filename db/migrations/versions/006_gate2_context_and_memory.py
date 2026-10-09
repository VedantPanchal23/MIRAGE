"""Add Gate 2 Context Assurance and Governed Memory schemas with RLS.

Revision ID: 006_gate2_context_and_memory
Revises: 005_control_plane_identity
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006_gate2_context_and_memory"
down_revision: str | None = "005_control_plane_identity"
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
    # 1. Add context_sources ledger column to ai_transactions
    op.add_column(
        "ai_transactions",
        sa.Column("context_sources", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    # 2. Create governed_memories table
    op.create_table(
        "governed_memories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="ORGANIZATIONAL"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("attestation_status", sa.String(32), nullable=False, server_default="NONE"),
        sa.Column("attested_by", sa.String(64), nullable=True),
        sa.Column("taint", sa.String(64), nullable=False, server_default="TAINT_INTERNAL"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_governed_memories_tenant_id", "governed_memories", ["tenant_id"])
    op.create_index("ix_governed_memories_owner_id", "governed_memories", ["owner_id"])
    op.create_index("ix_governed_memories_content_hash", "governed_memories", ["content_hash"])
    op.create_index("ix_governed_memories_memory_type", "governed_memories", ["memory_type"])

    # 3. Enforce PostgreSQL Row-Level Security on governed_memories
    _tenant_rls("governed_memories")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_governed_memories ON governed_memories")
    op.drop_table("governed_memories")
    op.drop_column("ai_transactions", "context_sources")
