"""Add Gate 5 Outcome Assurance and Reality Verification records with RLS.

Revision ID: 009_gate5_outcome_assurance
Revises: 008_gate4_output_assurance
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "009_gate5_outcome_assurance"
down_revision: str | None = "008_gate4_output_assurance"
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
    # Create outcome_verification_records table
    op.create_table(
        "outcome_verification_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("action_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observability_class", sa.String(32), nullable=False),
        sa.Column("outcome_status", sa.String(32), nullable=False),
        sa.Column("epistemic_confidence", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("verifier_adapter", sa.String(64), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expected_postconditions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_state", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("discrepancies", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reconciliation_notes", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("verification_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("target_environment", sa.String(32), nullable=False, server_default=sa.text("'DEFAULT'")),
        sa.Column("contract_binding_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outcome_verification_records_tenant_id", "outcome_verification_records", ["tenant_id"])
    op.create_index(
        "ix_outcome_verification_records_transaction_id", "outcome_verification_records", ["transaction_id"]
    )
    op.create_index("ix_outcome_verification_records_action_id", "outcome_verification_records", ["action_id"])
    op.create_index(
        "ix_outcome_verification_records_outcome_status", "outcome_verification_records", ["outcome_status"]
    )
    op.create_index(
        "ix_outcome_verification_records_idempotency_key",
        "outcome_verification_records",
        ["tenant_id", "idempotency_key"],
    )

    _tenant_rls("outcome_verification_records")


def downgrade() -> None:
    op.drop_table("outcome_verification_records")
