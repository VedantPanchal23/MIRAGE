"""Bootstrap System Root Tenant and Super Admin Identity in MIRAGE.

Ensures the foundational 'system' tenant, super admin user, and root audit ledger
are provisioned in PostgreSQL so administrative APIs can authenticate properly.
"""

import subprocess
import sys

BOOTSTRAP_SQL = """
BEGIN;
INSERT INTO tenants (
    id, name, api_key_hash, tier, scs_enabled, pii_detection_enabled, created_at, status, updated_at
)
VALUES (
    'system',
    'MIRAGE System Root',
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'enterprise',
    true,
    true,
    NOW(),
    'ACTIVE',
    NOW()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, tenant_id, external_subject, display_name, role, active, created_at)
VALUES ('user_system_super_admin', 'system', 'staging_super_admin', 'Staging Super Admin', 'super_admin', true, NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO actor_identities (id, tenant_id, subject, user_id, principal_type, role, active, created_at)
VALUES (
    'id_system_super_admin',
    'system',
    'staging_super_admin',
    'user_system_super_admin',
    'user',
    'super_admin',
    true,
    NOW()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO tenant_audit_ledgers (tenant_id, head_chain_hash, sequence_number, created_at, updated_at)
VALUES ('system', '0000000000000000000000000000000000000000000000000000000000000000', 0, NOW(), NOW())
ON CONFLICT (tenant_id) DO NOTHING;
COMMIT;
"""


def bootstrap_via_docker() -> bool:
    print("[BOOTSTRAP] Ensuring system tenant and super admin exist in PostgreSQL...")
    cmd = [
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "mirage", "-d", "mirage_db", "-c", BOOTSTRAP_SQL
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print(f"[BOOTSTRAP ERROR] psql failed:\n{res.stderr}")
        return False
    print("[BOOTSTRAP] System root tenant, super admin identity, and genesis ledger verified.")
    return True


if __name__ == "__main__":
    ok = bootstrap_via_docker()
    sys.exit(0 if ok else 1)
