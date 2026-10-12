"""Phase 5.1.1: Financial integrity check constraints, durable accounting incidents, and privacy attestation lifecycle.

Revision ID: 014_phase5_1_1_financial_integrity
Revises: 013_phase5_1_hardening
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_financial_integrity"
down_revision: str | None = "013_phase5_1_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Non-negative check constraints on tenant_budgets
    op.create_check_constraint(
        "ck_tenant_budget_reserved_non_negative",
        "tenant_budgets",
        "reserved_micros >= 0",
    )
    op.create_check_constraint(
        "ck_tenant_budget_spent_non_negative",
        "tenant_budgets",
        "spent_micros >= 0",
    )
    op.create_check_constraint(
        "ck_tenant_budget_allocated_non_negative",
        "tenant_budgets",
        "allocated_micros >= 0",
    )

    # 2. Add privacy attestation expiration and revocation columns to model_registry
    op.add_column(
        "model_registry",
        sa.Column("privacy_attestation_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_registry",
        sa.Column("privacy_attestation_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 3. Create accounting_incidents table for durable financial drift and discrepancy auditing
    json_type = (
        postgresql.JSONB(astext_type=sa.Text())
        if op.get_bind().dialect.name == "postgresql"
        else sa.JSON()
    )
    op.create_table(
        "accounting_incidents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reservation_id", sa.String(64), nullable=True, index=True),
        sa.Column("transaction_id", sa.String(64), nullable=True, index=True),
        sa.Column("incident_type", sa.String(64), nullable=False, index=True),
        sa.Column("expected_micros", sa.BigInteger(), nullable=True),
        sa.Column("actual_micros", sa.BigInteger(), nullable=True),
        sa.Column("details", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. Seed future attestation expiration for existing verified models
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE model_registry
            SET privacy_attestation_expires_at = NOW() + INTERVAL '365 days'
            WHERE privacy_verified_at IS NOT NULL;
            """
        )


def downgrade() -> None:
    op.drop_table("accounting_incidents")
    op.drop_column("model_registry", "privacy_attestation_revoked_at")
    op.drop_column("model_registry", "privacy_attestation_expires_at")
    op.drop_constraint("ck_tenant_budget_allocated_non_negative", "tenant_budgets", type_="check")
    op.drop_constraint("ck_tenant_budget_spent_non_negative", "tenant_budgets", type_="check")
    op.drop_constraint("ck_tenant_budget_reserved_non_negative", "tenant_budgets", type_="check")
