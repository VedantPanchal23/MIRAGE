"""Enforce NOT NULL constraint on audit_logs.sequence_number.

Revision ID: 011_enforce_audit_logs_sequence_not_null
Revises: 010_audit_ledger_checkpoints
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_audit_seq_not_null"
down_revision: str | None = "010_audit_ledger_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Backfill any existing audit_logs that may have NULL sequence_number
    op.execute(
        """
        WITH numbered_logs AS (
            SELECT entry_id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at ASC, entry_id ASC) as seq
            FROM audit_logs
        )
        UPDATE audit_logs
        SET sequence_number = numbered_logs.seq
        FROM numbered_logs
        WHERE audit_logs.entry_id = numbered_logs.entry_id AND audit_logs.sequence_number IS NULL;
        """
    )

    # 2. Synchronize tenant_audit_ledgers head for all tenants with audit logs
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
        ORDER BY tenant_id, sequence_number DESC
        ON CONFLICT (tenant_id) DO UPDATE
        SET head_entry_id = EXCLUDED.head_entry_id,
            head_chain_hash = EXCLUDED.head_chain_hash,
            sequence_number = EXCLUDED.sequence_number,
            updated_at = EXCLUDED.updated_at;
        """
    )

    # 3. Enforce NOT NULL constraint on audit_logs.sequence_number
    op.alter_column(
        "audit_logs",
        "sequence_number",
        nullable=False,
        server_default=sa.text("1"),
        existing_type=sa.BigInteger(),
    )


def downgrade() -> None:
    # Relax NOT NULL constraint on sequence_number
    op.alter_column(
        "audit_logs",
        "sequence_number",
        nullable=True,
        server_default=None,
        existing_type=sa.BigInteger(),
    )
