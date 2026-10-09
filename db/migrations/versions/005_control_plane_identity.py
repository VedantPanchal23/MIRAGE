"""Add the MIRAGE 3.0 control-plane identity and transaction foundation.

Revision ID: 005_control_plane_identity
Revises: 004_kb_documents
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005_control_plane_identity"
down_revision: str | None = "004_kb_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_rls(table: str, writable: bool = True) -> None:
    """Attach a fail-closed tenant RLS policy to a control-plane table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    if writable:
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL "
            "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))"
        )
    else:
        op.execute(
            f"CREATE POLICY tenant_select_{table} ON {table} FOR SELECT "
            "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))"
        )


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("event_type", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_identity_id", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("transaction_id", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("decision", sa.String(32), nullable=True))
    op.add_column("audit_logs", sa.Column("policy_reference", sa.String(128), nullable=True))
    op.add_column("audit_logs", sa.Column("capability_id", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(
        "audit_logs", sa.Column("event_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb"))
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "external_subject", name="uq_users_tenant_subject"),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_autonomy_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
    )
    op.create_table(
        "actor_identities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "subject", name="uq_actor_identities_tenant_subject"),
    )
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "identity_id", sa.String(64), sa.ForeignKey("actor_identities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "policies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_policies_tenant_name_version"),
    )
    op.create_table(
        "capabilities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_id", sa.String(64), sa.ForeignKey("actor_identities.id", ondelete="CASCADE")),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.id", ondelete="CASCADE")),
        sa.Column("capability_type", sa.String(128), nullable=False),
        sa.Column("resource_scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("constraints", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_autonomy_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("identity_id IS NOT NULL OR agent_id IS NOT NULL", name="ck_capability_subject"),
    )
    op.create_table(
        "budgets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_cost_micros", sa.Integer(), nullable=False),
        sa.Column("max_risk", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_transactions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "actor_identity_id",
            sa.String(64),
            sa.ForeignKey("actor_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.id", ondelete="RESTRICT")),
        sa.Column("parent_transaction_id", sa.String(64), sa.ForeignKey("ai_transactions.id", ondelete="RESTRICT")),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("taint_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("policies.id", ondelete="RESTRICT")),
        sa.Column("budget_id", sa.String(64), sa.ForeignKey("budgets.id", ondelete="RESTRICT")),
        sa.Column("final_disposition", sa.String(32)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_transactions_tenant_idempotency"),
    )
    for table in (
        "users",
        "agents",
        "actor_identities",
        "api_credentials",
        "policies",
        "capabilities",
        "budgets",
        "ai_transactions",
    ):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        _tenant_rls(table)

    # Authentication lookup intentionally crosses tenant RLS only inside this narrowly scoped
    # SECURITY DEFINER function. It verifies that the signed routing assertion matches the
    # persisted binding before returning an active identity; callers never query identities globally.
    op.execute(
        """
        CREATE FUNCTION mirage_resolve_jwt_identity(p_subject text, p_tenant_id text)
        RETURNS TABLE(identity_id text, tenant_id text, role text, principal_type text, user_id text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT ai.id, ai.tenant_id, ai.role, ai.principal_type, COALESCE(ai.user_id, ai.subject)
            FROM actor_identities ai
            JOIN tenants t ON t.id = ai.tenant_id
            WHERE ai.subject = p_subject AND ai.tenant_id = p_tenant_id
              AND ai.active = true
            LIMIT 1
        $$;
        CREATE FUNCTION mirage_resolve_api_credential(p_key_hash text)
        RETURNS TABLE(identity_id text, tenant_id text, role text, principal_type text, user_id text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT ai.id, ai.tenant_id, ai.role, ai.principal_type, COALESCE(ai.user_id, ai.subject)
            FROM api_credentials c
            JOIN actor_identities ai ON ai.id = c.identity_id AND ai.tenant_id = c.tenant_id
            JOIN tenants t ON t.id = c.tenant_id
            WHERE c.key_hash = p_key_hash AND c.revoked_at IS NULL
              AND (c.expires_at IS NULL OR c.expires_at > now()) AND ai.active = true
            LIMIT 1
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS mirage_resolve_api_credential(text)")
    op.execute("DROP FUNCTION IF EXISTS mirage_resolve_jwt_identity(text, text)")
    for table in (
        "ai_transactions",
        "budgets",
        "capabilities",
        "policies",
        "api_credentials",
        "actor_identities",
        "agents",
        "users",
    ):
        op.drop_table(table)
    for column in (
        "event_payload",
        "reason",
        "capability_id",
        "policy_reference",
        "decision",
        "transaction_id",
        "actor_identity_id",
        "event_type",
    ):
        op.drop_column("audit_logs", column)
