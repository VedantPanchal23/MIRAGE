"""Final Phase Package 2: Governed external MCP server registry with RLS, trust status, and tool binding.

Revision ID: 023_governed_mcp_servers
Revises: 022_tenant_api_keys
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "023_governed_mcp_servers"
down_revision: str | None = "022_tenant_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = JSONB() if is_postgres else sa.JSON()

    # 1. Create mcp_servers table
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("transport_type", sa.String(32), server_default="STDIO", nullable=False),
        sa.Column("connection_config", json_type, server_default=sa.text("'{}'::jsonb" if is_postgres else "'{}'"), nullable=False),
        sa.Column("trust_status", sa.String(32), server_default="PENDING_APPROVAL", nullable=False),
        sa.Column("permitted_capabilities", json_type, server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"), nullable=False),
        sa.Column("egress_allowlist", json_type, server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="30", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_mcp_servers_tenant_name"),
    )
    op.create_index("ix_mcp_servers_trust_status", "mcp_servers", ["trust_status"])
    op.create_index("ix_mcp_servers_tenant_status", "mcp_servers", ["tenant_id", "trust_status"])

    # 2. Add mcp_server_id foreign key column to tool_registry
    op.add_column(
        "tool_registry",
        sa.Column(
            "mcp_server_id",
            sa.String(64),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_tool_registry_mcp_server_id", "tool_registry", ["mcp_server_id"])

    # 3. Enable and enforce Row-Level Security for mcp_servers in PostgreSQL
    if is_postgres:
        op.execute(
            """
            ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
            ALTER TABLE mcp_servers FORCE ROW LEVEL SECURITY;

            DROP POLICY IF EXISTS tenant_isolation_mcp_servers ON mcp_servers;
            CREATE POLICY tenant_isolation_mcp_servers ON mcp_servers
                FOR ALL
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

            GRANT SELECT, INSERT, UPDATE, DELETE ON mcp_servers TO mirage_app;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            DROP POLICY IF EXISTS tenant_isolation_mcp_servers ON mcp_servers;
            """
        )

    op.drop_index("ix_tool_registry_mcp_server_id", table_name="tool_registry")
    op.drop_column("tool_registry", "mcp_server_id")

    op.drop_index("ix_mcp_servers_tenant_status", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_trust_status", table_name="mcp_servers")
    op.drop_table("mcp_servers")
