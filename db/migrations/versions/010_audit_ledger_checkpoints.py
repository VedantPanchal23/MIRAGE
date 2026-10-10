"""Add Tenant Audit Ledgers and Persistent Authenticated Checkpoints with RLS.

Revision ID: 010_audit_ledger_checkpoints
Revises: 009_gate5_outcome_assurance
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_audit_ledger_checkpoints"
down_revision: str | None = "009_gate5_outcome_assurance"
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
    # 1. Create tenant_audit_ledgers table for serialized ledger-head locking
    op.create_table(
        "tenant_audit_ledgers",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("head_entry_id", sa.String(64), nullable=True),
        sa.Column("head_chain_hash", sa.String(64), nullable=False, server_default=sa.text("'0' || repeat('0', 63)")),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    _tenant_rls("tenant_audit_ledgers")

    # 2. Add sequence_number column to audit_logs
    op.add_column(
        "audit_logs",
        sa.Column("sequence_number", sa.BigInteger(), nullable=True),
    )

    # Populate sequence_number for any existing audit_logs per tenant ordered by created_at, entry_id
    op.execute(
        """
        WITH numbered_logs AS (
            SELECT entry_id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at ASC, entry_id ASC) as seq
            FROM audit_logs
        )
        UPDATE audit_logs
        SET sequence_number = numbered_logs.seq
        FROM numbered_logs
        WHERE audit_logs.entry_id = numbered_logs.entry_id;
        """
    )

    # For tenants with existing audit logs, initialize tenant_audit_ledgers
    op.execute(
        """
        INSERT INTO tenant_audit_ledgers (tenant_id, head_entry_id, head_chain_hash, sequence_number, updated_at)
        SELECT DISTINCT ON (tenant_id)
            tenant_id,
            entry_id,
            chain_hash,
            sequence_number,
            created_at
        FROM audit_logs
        WHERE sequence_number IS NOT NULL
        ORDER BY tenant_id, sequence_number DESC
        ON CONFLICT (tenant_id) DO UPDATE
        SET head_entry_id = EXCLUDED.head_entry_id,
            head_chain_hash = EXCLUDED.head_chain_hash,
            sequence_number = EXCLUDED.sequence_number,
            updated_at = EXCLUDED.updated_at;
        """
    )

    # Add unique constraint on (tenant_id, sequence_number) to enforce no sequence forks/gaps for sequenced logs
    op.create_unique_constraint(
        "uq_audit_logs_tenant_sequence",
        "audit_logs",
        ["tenant_id", "sequence_number"],
    )

    # 3. Create audit_checkpoints table for persistent, authenticated trust anchors
    op.create_table(
        "audit_checkpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("ledger_identity", sa.String(64), nullable=False, server_default=sa.text("'audit_logs'")),
        sa.Column("signer_identity", sa.String(128), nullable=False),
        sa.Column("signature", sa.String(256), nullable=False),
        sa.Column("trust_tier", sa.String(32), nullable=False, server_default=sa.text("'LOCAL_CHECKPOINT'")),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_checkpoints_tenant_id", "audit_checkpoints", ["tenant_id"])
    op.create_index("ix_audit_checkpoints_checkpoint_hash", "audit_checkpoints", ["checkpoint_hash"])
    op.create_unique_constraint(
        "uq_audit_checkpoints_tenant_hash",
        "audit_checkpoints",
        ["tenant_id", "checkpoint_hash"],
    )
    _tenant_rls("audit_checkpoints")


def downgrade() -> None:
    op.drop_table("audit_checkpoints")
    op.drop_constraint("uq_audit_logs_tenant_sequence", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "sequence_number")
    op.drop_table("tenant_audit_ledgers")
