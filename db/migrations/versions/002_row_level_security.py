"""PostgreSQL Row-Level Security (RLS) policies for multi-tenant isolation.

Revision ID: 002_row_level_security
Revises: 001_initial_schema
Create Date: 2026-09-13 17:45:00.000000

Implements Security and Access Document Section 9.1:
- Row-Level Security (RLS) enabled and forced on verification_sessions, claims, audit_logs, and tenants
- Strict tenant isolation enforced via transaction-local setting
  NULLIF(current_setting('app.current_tenant_id', true), '')
- Immutable append-only audit_logs: SELECT and INSERT policies only; UPDATE and DELETE disallowed
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_row_level_security"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Verification Sessions RLS
    op.execute("ALTER TABLE verification_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE verification_sessions FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_sessions ON verification_sessions
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )

    # 2. Claims RLS
    op.execute("ALTER TABLE claims ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE claims FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_claims ON claims
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )

    # 3. Audit Logs RLS (Append-Only / Immutable: SELECT and INSERT only)
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_select_audit_logs ON audit_logs
            FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_insert_audit_logs ON audit_logs
            FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )

    # 4. Tenants Table RLS
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_tenants ON tenants
            FOR ALL
            USING (id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )


def downgrade() -> None:
    # Drop policies and disable RLS
    op.execute("DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants;")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS tenant_select_audit_logs ON audit_logs;")
    op.execute("DROP POLICY IF EXISTS tenant_insert_audit_logs ON audit_logs;")
    op.execute("ALTER TABLE audit_logs NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_claims ON claims;")
    op.execute("ALTER TABLE claims NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE claims DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_sessions ON verification_sessions;")
    op.execute("ALTER TABLE verification_sessions NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE verification_sessions DISABLE ROW LEVEL SECURITY;")
