"""Commercial & Governance: Outbound Webhook Subscriptions and Alerting Table.

Revision ID: 025_webhooks_table
Revises: 024_inquiries_table
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "025_webhooks_table"
down_revision: str | None = "024_inquiries_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = JSONB() if is_postgres else sa.JSON()

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("description", sa.String(512), server_default="", nullable=False),
        sa.Column("secret_key", sa.String(128), nullable=False),
        sa.Column(
            "event_types",
            json_type,
            server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_webhook_subscriptions_tenant_active", "webhook_subscriptions", ["tenant_id", "active"])

    if is_postgres:
        op.execute(
            """
            ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY;
            ALTER TABLE webhook_subscriptions FORCE ROW LEVEL SECURITY;

            DROP POLICY IF EXISTS tenant_isolation_webhook_subscriptions ON webhook_subscriptions;
            CREATE POLICY tenant_isolation_webhook_subscriptions ON webhook_subscriptions
                FOR ALL
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

            GRANT SELECT, INSERT, UPDATE, DELETE ON webhook_subscriptions TO mirage_app;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            DROP POLICY IF EXISTS tenant_isolation_webhook_subscriptions ON webhook_subscriptions;
            """
        )

    op.drop_index("ix_webhook_subscriptions_tenant_active", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
