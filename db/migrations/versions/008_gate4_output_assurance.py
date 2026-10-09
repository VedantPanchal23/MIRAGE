"""Add Gate 4 Output Assurance records with RLS.

Revision ID: 008_gate4_output_assurance
Revises: 007_gate3_action_governance
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008_gate4_output_assurance"
down_revision: str | None = "007_gate3_action_governance"
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
    # Create output_assurance_records table
    op.create_table(
        "output_assurance_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "transaction_id",
            sa.String(64),
            sa.ForeignKey("ai_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("original_output", sa.Text(), nullable=False),
        sa.Column("final_output", sa.Text(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("final_decision", sa.String(32), nullable=False),
        sa.Column("risk_tier", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("conformal_bounds", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("signal_attributions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("claims_payload", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("safety_result", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("factual_result", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("budget_consumed", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tier_path", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("escalation_reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("was_corrected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("correction_history", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("audit_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_output_assurance_records_tenant_id", "output_assurance_records", ["tenant_id"])
    op.create_index("ix_output_assurance_records_transaction_id", "output_assurance_records", ["transaction_id"])
    op.create_index("ix_output_assurance_records_output_hash", "output_assurance_records", ["output_hash"])

    _tenant_rls("output_assurance_records")


def downgrade() -> None:
    op.drop_table("output_assurance_records")
