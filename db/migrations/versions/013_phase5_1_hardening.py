"""Phase 5.1 Hardening: deployment-aware models, robust pricing constraints, and settlement auditability.

Revision ID: 013_phase5_1_hardening
Revises: 012_model_routing_and_budgets
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_phase5_1_hardening"
down_revision: str | None = "012_model_routing_and_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update model_registry with deployment-aware privacy metadata
    op.add_column(
        "model_registry",
        sa.Column("deployment_type", sa.String(64), server_default="cloud_shared", nullable=False),
    )
    op.add_column(
        "model_registry",
        sa.Column("privacy_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_registry",
        sa.Column("privacy_policy_version", sa.String(32), server_default="v1.0", nullable=True),
    )
    op.add_column(
        "model_registry",
        sa.Column("endpoint_url", sa.String(255), nullable=True),
    )

    # 2. Update model_pricing_profiles constraints
    op.create_unique_constraint(
        "uq_model_pricing_model_effective",
        "model_pricing_profiles",
        ["model_id", "effective_date"],
    )

    # 3. Update budget_reservations with attempt tracking
    op.add_column(
        "budget_reservations",
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "budget_reservations",
        sa.Column("selected_provider", sa.String(64), nullable=True),
    )
    op.add_column(
        "budget_reservations",
        sa.Column("selected_model", sa.String(128), nullable=True),
    )

    # 4. Update transaction_cost_records with pricing provenance and idempotency
    op.add_column(
        "transaction_cost_records",
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "transaction_cost_records",
        sa.Column("pricing_profile_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "transaction_cost_records",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_transaction_cost_idempotency",
        "transaction_cost_records",
        ["tenant_id", "transaction_id", "attempt_number"],
    )

    # Seed verified privacy metadata for baseline models
    op.execute(
        """
        UPDATE model_registry
        SET deployment_type = 'air_gapped',
            privacy_verified_at = NOW(),
            privacy_policy_version = 'v1.0'
        WHERE id IN ('mock-frontier', 'mock-capable', 'mock-specialized');
        """
    )
    op.execute(
        """
        UPDATE model_registry
        SET deployment_type = 'on_prem_local',
            privacy_verified_at = NOW(),
            privacy_policy_version = 'v1.0',
            endpoint_url = 'http://localhost:11434'
        WHERE id = 'allam-2-7b';
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_transaction_cost_idempotency", "transaction_cost_records", type_="unique")
    op.drop_column("transaction_cost_records", "idempotency_key")
    op.drop_column("transaction_cost_records", "pricing_profile_id")
    op.drop_column("transaction_cost_records", "attempt_number")

    op.drop_column("budget_reservations", "selected_model")
    op.drop_column("budget_reservations", "selected_provider")
    op.drop_column("budget_reservations", "attempt_number")

    op.drop_constraint("uq_model_pricing_model_effective", "model_pricing_profiles", type_="unique")

    op.drop_column("model_registry", "endpoint_url")
    op.drop_column("model_registry", "privacy_policy_version")
    op.drop_column("model_registry", "privacy_verified_at")
    op.drop_column("model_registry", "deployment_type")
