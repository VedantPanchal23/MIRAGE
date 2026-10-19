"""Final Phase Package 1: Tenant lifecycle status and enhanced API key management with RLS and tenant resolution.

Revision ID: 022_tenant_api_keys
Revises: 021_phase8_fencing_hard
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "022_tenant_api_keys"
down_revision: str | None = "021_phase8_fencing_hard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = JSONB() if is_postgres else sa.JSON()

    # 1. Enhance tenants table with authoritative lifecycle status
    op.add_column(
        "tenants",
        sa.Column("status", sa.String(32), server_default="ACTIVE", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("suspension_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])

    # 2. Enhance api_credentials table with metadata, prefixes, and scopes
    op.add_column(
        "api_credentials",
        sa.Column("name", sa.String(255), server_default="Default API Key", nullable=False),
    )
    op.add_column(
        "api_credentials",
        sa.Column("key_prefix", sa.String(16), server_default="mirage_live_", nullable=False),
    )
    scopes_default = sa.text("'[\"*\"]'::jsonb" if is_postgres else "'[\"*\"]'")
    op.add_column(
        "api_credentials",
        sa.Column("scopes", json_type, server_default=scopes_default, nullable=False),
    )
    op.add_column(
        "api_credentials",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_credentials_tenant_created", "api_credentials", ["tenant_id", "created_at"])
    op.create_index("ix_api_credentials_key_prefix", "api_credentials", ["key_prefix"])

    # 3. Update PostgreSQL resolution functions to strictly enforce active tenant status
    if is_postgres:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION mirage_resolve_api_credential(p_key_hash text)
            RETURNS TABLE(identity_id text, tenant_id text, role text, principal_type text, user_id text)
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
                SELECT ai.id, ai.tenant_id, ai.role, ai.principal_type, COALESCE(ai.user_id, ai.subject)
                FROM api_credentials c
                JOIN actor_identities ai ON ai.id = c.identity_id AND ai.tenant_id = c.tenant_id
                JOIN tenants t ON t.id = c.tenant_id
                WHERE c.key_hash = p_key_hash
                  AND c.revoked_at IS NULL
                  AND (c.expires_at IS NULL OR c.expires_at > now())
                  AND ai.active = true
                  AND t.status = 'ACTIVE'
                LIMIT 1
            $$;

            CREATE OR REPLACE FUNCTION mirage_resolve_jwt_identity(p_subject text, p_tenant_id text)
            RETURNS TABLE(identity_id text, tenant_id text, role text, principal_type text, user_id text)
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
                SELECT ai.id, ai.tenant_id, ai.role, ai.principal_type, COALESCE(ai.user_id, ai.subject)
                FROM actor_identities ai
                JOIN tenants t ON t.id = ai.tenant_id
                WHERE ai.subject = p_subject
                  AND ai.tenant_id = p_tenant_id
                  AND ai.active = true
                  AND t.status = 'ACTIVE'
                LIMIT 1
            $$;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION mirage_resolve_api_credential(p_key_hash text)
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

            CREATE OR REPLACE FUNCTION mirage_resolve_jwt_identity(p_subject text, p_tenant_id text)
            RETURNS TABLE(identity_id text, tenant_id text, role text, principal_type text, user_id text)
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
                SELECT ai.id, ai.tenant_id, ai.role, ai.principal_type, COALESCE(ai.user_id, ai.subject)
                FROM actor_identities ai
                JOIN tenants t ON t.id = ai.tenant_id
                WHERE ai.subject = p_subject AND ai.tenant_id = p_tenant_id
                  AND ai.active = true
                LIMIT 1
            $$;
            """
        )

    op.drop_index("ix_api_credentials_key_prefix", table_name="api_credentials")
    op.drop_index("ix_api_credentials_tenant_created", table_name="api_credentials")
    op.drop_column("api_credentials", "last_used_at")
    op.drop_column("api_credentials", "scopes")
    op.drop_column("api_credentials", "key_prefix")
    op.drop_column("api_credentials", "name")

    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_column("tenants", "updated_at")
    op.drop_column("tenants", "suspension_reason")
    op.drop_column("tenants", "status")
