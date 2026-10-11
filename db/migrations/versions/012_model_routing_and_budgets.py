"""Model registry, pricing profiles, tenant budgets, and transaction cost records.

Revision ID: 012_model_routing_and_budgets
Revises: 011_audit_seq_not_null
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_model_routing_and_budgets"
down_revision: str | None = "011_audit_seq_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. model_registry
    op.create_table(
        "model_registry",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("family", sa.String(64), server_default="general", nullable=False),
        sa.Column("tier", sa.String(32), server_default="CAPABLE", nullable=False),
        sa.Column("context_window", sa.Integer(), server_default="128000", nullable=False),
        sa.Column("supports_tools", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("supports_vision", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_structured_output", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("supports_system_prompt", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_zero_retention", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reliability_index", sa.Float(), server_default="0.85", nullable=False),
        sa.Column("expected_latency_ms", sa.Float(), server_default="800.0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 2. model_pricing_profiles
    op.create_table(
        "model_pricing_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("model_id", sa.String(128), sa.ForeignKey("model_registry.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_date", sa.String(32), server_default="2026-01-01", nullable=False),
        sa.Column("currency", sa.String(16), server_default="USD", nullable=False),
        sa.Column("input_cost_per_million_micros", sa.BigInteger(), nullable=False),
        sa.Column("output_cost_per_million_micros", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_cost_per_million_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_pricing_profiles_model_id", "model_pricing_profiles", ["model_id"])

    # 3. tenant_budgets
    op.create_table(
        "tenant_budgets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(16), server_default="USD", nullable=False),
        sa.Column("total_budget_micros", sa.BigInteger(), server_default="100000000", nullable=False),
        sa.Column("allocated_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("spent_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reset_period", sa.String(32), server_default="MONTHLY", nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hard_limit", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_budgets_tenant_id"),
    )
    op.create_index("ix_tenant_budgets_tenant_id", "tenant_budgets", ["tenant_id"])

    # 4. budget_reservations
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.String(64), nullable=False),
        sa.Column("reservation_key", sa.String(255), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), server_default="RESERVED", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "reservation_key", name="uq_budget_reservations_tenant_key"),
    )
    op.create_index("ix_budget_reservations_tenant_id", "budget_reservations", ["tenant_id"])
    op.create_index("ix_budget_reservations_transaction_id", "budget_reservations", ["transaction_id"])
    op.create_index("ix_budget_reservations_status", "budget_reservations", ["status"])
    op.create_index("ix_budget_reservations_expires_at", "budget_reservations", ["expires_at"])

    # 5. transaction_cost_records
    op.create_table(
        "transaction_cost_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("stage", sa.String(64), server_default="PRIMARY_INFERENCE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transaction_cost_records_tenant_id", "transaction_cost_records", ["tenant_id"])
    op.create_index("ix_transaction_cost_records_transaction_id", "transaction_cost_records", ["transaction_id"])
    op.create_index("ix_transaction_cost_records_created_at", "transaction_cost_records", ["created_at"])

    # Seed baseline models and pricing
    op.execute(
        """
        INSERT INTO model_registry (
            id, provider, family, tier, context_window, supports_tools, supports_vision,
            supports_structured_output, supports_system_prompt, is_zero_retention,
            reliability_index, expected_latency_ms, active
        ) VALUES
        ('mock-frontier', 'mock', 'mock', 'FRONTIER', 128000, true, true, true, true, true, 0.95, 50.0, true),
        ('mock-capable', 'mock', 'mock', 'CAPABLE', 128000, true, false, true, true, true, 0.85, 25.0, true),
        ('mock-specialized', 'mock', 'mock', 'SPECIALIZED', 32768, false, false, false, false, true, 0.75, 10.0, true),
        ('gpt-4o', 'openai', 'openai', 'FRONTIER', 128000, true, true, true, true, false, 0.94, 750.0, true),
        ('gpt-4o-mini', 'openai', 'openai', 'CAPABLE', 128000, true, true, true, true, false, 0.86, 350.0, true),
        ('claude-3-5-sonnet-20241022', 'anthropic', 'anthropic', 'FRONTIER',
         200000, true, true, true, true, false, 0.96, 850.0, true),
        ('claude-3-haiku-20240307', 'anthropic', 'anthropic', 'CAPABLE',
         200000, true, true, true, true, false, 0.84, 300.0, true),
        ('gemini-1.5-pro', 'google', 'google', 'FRONTIER', 1000000, true, true, true, true, false, 0.93, 900.0, true),
        ('gemini-1.5-flash', 'google', 'google', 'CAPABLE', 1000000, true, true, true, true, false, 0.85, 250.0, true),
        ('allam-2-7b', 'ollama', 'local', 'CAPABLE', 32768, true, false, true, true, true, 0.82, 180.0, true)
        ON CONFLICT (id) DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO model_pricing_profiles (
            id, model_id, effective_date, currency, input_cost_per_million_micros,
            output_cost_per_million_micros, cached_input_cost_per_million_micros, is_active
        ) VALUES
        ('price_mock_frontier', 'mock-frontier', '2026-01-01', 'USD', 2500000, 10000000, 1250000, true),
        ('price_mock_capable', 'mock-capable', '2026-01-01', 'USD', 150000, 600000, 75000, true),
        ('price_mock_specialized', 'mock-specialized', '2026-01-01', 'USD', 50000, 150000, 25000, true),
        ('price_gpt_4o', 'gpt-4o', '2026-01-01', 'USD', 2500000, 10000000, 1250000, true),
        ('price_gpt_4o_mini', 'gpt-4o-mini', '2026-01-01', 'USD', 150000, 600000, 75000, true),
        ('price_claude_35_sonnet', 'claude-3-5-sonnet-20241022', '2026-01-01', 'USD', 3000000, 15000000, 300000, true),
        ('price_claude_3_haiku', 'claude-3-haiku-20240307', '2026-01-01', 'USD', 250000, 1250000, 25000, true),
        ('price_gemini_15_pro', 'gemini-1.5-pro', '2026-01-01', 'USD', 1250000, 5000000, 312500, true),
        ('price_gemini_15_flash', 'gemini-1.5-flash', '2026-01-01', 'USD', 75000, 300000, 18750, true),
        ('price_allam_2_7b', 'allam-2-7b', '2026-01-01', 'USD', 0, 0, 0, true)
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("transaction_cost_records")
    op.drop_table("budget_reservations")
    op.drop_table("tenant_budgets")
    op.drop_table("model_pricing_profiles")
    op.drop_table("model_registry")
