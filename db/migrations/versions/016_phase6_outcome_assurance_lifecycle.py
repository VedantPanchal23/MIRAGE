"""Phase 6: Outcome Assurance, Outcome Contract lifecycle, and Evidence Provenance.

Revision ID: 016_phase6_outcome_assurance
Revises: 015_routing_remediation
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "016_phase6_outcome_assurance"
down_revision: str | None = "015_routing_remediation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Add outcome contract fields to action_contracts
    op.add_column(
        "action_contracts",
        sa.Column("requires_outcome_assurance", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "action_contracts",
        sa.Column("outcome_contract", JSONB() if is_postgres else sa.JSON(), nullable=True),
    )
    op.add_column(
        "action_contracts",
        sa.Column("outcome_status", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_action_contracts_outcome_status",
        "action_contracts",
        ["outcome_status"],
    )

    # 2. Add evidence provenance, deadline, and escalation fields to outcome_verification_records
    op.add_column(
        "outcome_verification_records",
        sa.Column("evidence_source", sa.String(128), nullable=True),
    )
    op.add_column(
        "outcome_verification_records",
        sa.Column("evidence_digest", sa.String(64), nullable=True),
    )
    op.add_column(
        "outcome_verification_records",
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outcome_verification_records",
        sa.Column("verification_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outcome_verification_records",
        sa.Column("escalation_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "outcome_verification_records",
        sa.Column("escalation_notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_outcome_verification_records_escalation_status",
        "outcome_verification_records",
        ["escalation_status"],
    )
    op.create_index(
        "ix_outcome_verification_records_deadline",
        "outcome_verification_records",
        ["verification_deadline"],
    )

    # 3. Ensure permissions for mirage_app role
    if is_postgres:
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON
                        action_contracts,
                        outcome_verification_records
                    TO mirage_app;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    op.drop_index("ix_outcome_verification_records_deadline", table_name="outcome_verification_records")
    op.drop_index("ix_outcome_verification_records_escalation_status", table_name="outcome_verification_records")
    op.drop_column("outcome_verification_records", "escalation_notes")
    op.drop_column("outcome_verification_records", "escalation_status")
    op.drop_column("outcome_verification_records", "verification_deadline")
    op.drop_column("outcome_verification_records", "observed_at")
    op.drop_column("outcome_verification_records", "evidence_digest")
    op.drop_column("outcome_verification_records", "evidence_source")

    op.drop_index("ix_action_contracts_outcome_status", table_name="action_contracts")
    op.drop_column("action_contracts", "outcome_status")
    op.drop_column("action_contracts", "outcome_contract")
    op.drop_column("action_contracts", "requires_outcome_assurance")
