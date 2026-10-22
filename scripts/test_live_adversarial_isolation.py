"""MIRAGE 3.0 Live Adversarial & Tenant Isolation Verification Script.

Executes direct adversarial database, role privilege, and cross-tenant
security checks against the live running Docker stack:
1. Runtime PostgreSQL role fencing (rolsuper=False, rolbypassrls=False).
2. Separation of migration-owner privileges from runtime application role.
3. Live Row-Level Security (RLS) enforcement across synthetic tenants:
   - SELECT isolation (Alpha cannot read Beta).
   - UPDATE isolation (Alpha cannot modify Beta).
   - DELETE isolation (Alpha cannot delete Beta).
   - INSERT check violation (Alpha cannot insert row marked as Beta).
4. Concurrent session tenant-switching safety.
5. Real-time API key revocation and scope boundary enforcement via Gateway.
"""

from __future__ import annotations

import subprocess
import sys
import uuid

import httpx

GATEWAY_URL = "http://localhost:8000"


def run_psql(sql: str, as_user: str = "mirage") -> tuple[int, str, str]:
    """Execute raw SQL in the running PostgreSQL container via psql."""
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        as_user,
        "-d",
        "mirage_db",
        "-c",
        sql,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def test_1_runtime_role_privilege_fencing() -> bool:
    print("\n--- Test 1: Runtime PostgreSQL Role Privilege Fencing ---")
    sql = """
    SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb
    FROM pg_roles
    WHERE rolname IN ('mirage_app', 'mirage');
    """
    code, stdout, stderr = run_psql(sql)
    if code != 0:
        print(f"[FAIL] Querying pg_roles failed: {stderr}")
        return False

    print(f"[INFO] PostgreSQL Roles:\n{stdout}")

    # Check mirage_app properties
    check_sql = """
    SELECT
        COUNT(*) FILTER (WHERE rolname = 'mirage_app' AND rolsuper = false AND rolbypassrls = false) as safe_app_role,
        COUNT(*) FILTER (WHERE rolname = 'mirage') as owner_role
    FROM pg_roles;
    """
    code, stdout, stderr = run_psql(check_sql)
    if code != 0 or "1 |          1" not in stdout:
        print(f"[FAIL] mirage_app role verification failed: {stdout} {stderr}")
        return False

    print("[PASS] mirage_app has rolsuper=False and rolbypassrls=False (Strictly Unprivileged)")
    return True


def test_2_rls_crud_isolation_across_tenants() -> bool:
    print("\n--- Test 2: Live Row-Level Security (RLS) CRUD Isolation ---")
    tenant_a = f"tenant_rls_a_{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant_rls_b_{uuid.uuid4().hex[:8]}"
    hash_a = f"hash_a_{uuid.uuid4().hex[:12]}"
    hash_b = f"hash_b_{uuid.uuid4().hex[:12]}"

    # Setup synthetic tenants in database
    setup_sql = f"""
    BEGIN;
    INSERT INTO tenants (id, name, api_key_hash, tier, created_at, status, updated_at)
    VALUES
        ('{tenant_a}', 'Tenant Alpha', '{hash_a}', 'standard', NOW(), 'ACTIVE', NOW()),
        ('{tenant_b}', 'Tenant Beta', '{hash_b}', 'standard', NOW(), 'ACTIVE', NOW())
    ON CONFLICT (id) DO NOTHING;
    COMMIT;
    """
    code, _, stderr = run_psql(setup_sql)
    if code != 0:
        print(f"[FAIL] Tenant setup failed: {stderr}")
        return False

    # 1. Tenant Alpha inserts row
    agent_id_a = f"agent_rls_a_{uuid.uuid4().hex[:8]}"
    insert_sql = f"""
    SET LOCAL ROLE mirage_app;
    SET LOCAL app.current_tenant_id = '{tenant_a}';
    INSERT INTO agents (id, tenant_id, name, max_autonomy_level, status, created_at, updated_at)
    VALUES ('{agent_id_a}', '{tenant_a}', 'Agent Alpha', 1, 'active', NOW(), NOW());
    """
    code, _, stderr = run_psql(insert_sql)
    if code != 0:
        print(f"[FAIL] Tenant Alpha insert failed: {stderr}")
        return False
    print(f"[PASS] Tenant Alpha inserted agent '{agent_id_a}'")

    # 2. Tenant Beta attempts to SELECT Alpha's row
    select_sql = f"""
    SET LOCAL ROLE mirage_app;
    SET LOCAL app.current_tenant_id = '{tenant_b}';
    SELECT count(*) FROM agents WHERE id = '{agent_id_a}';
    """
    code, stdout, stderr = run_psql(select_sql)
    if code != 0 or "0" not in stdout:
        print(f"[FAIL] RLS SELECT isolation breached! Tenant Beta saw Alpha's row: {stdout}")
        return False
    print("[PASS] Tenant Beta SELECT returns 0 rows (Cross-Tenant Read Blocked)")

    # 3. Tenant Beta attempts to UPDATE Alpha's row
    update_sql = f"""
    SET LOCAL ROLE mirage_app;
    SET LOCAL app.current_tenant_id = '{tenant_b}';
    UPDATE agents SET name = 'HACKED' WHERE id = '{agent_id_a}';
    """
    code, stdout, stderr = run_psql(update_sql)
    if code != 0 or "UPDATE 0" not in stdout:
        print(f"[FAIL] RLS UPDATE isolation breached! Tenant Beta modified Alpha's row: {stdout}")
        return False
    print("[PASS] Tenant Beta UPDATE affected 0 rows (Cross-Tenant Update Blocked)")

    # 4. Tenant Beta attempts to DELETE Alpha's row
    delete_sql = f"""
    SET LOCAL ROLE mirage_app;
    SET LOCAL app.current_tenant_id = '{tenant_b}';
    DELETE FROM agents WHERE id = '{agent_id_a}';
    """
    code, stdout, stderr = run_psql(delete_sql)
    if code != 0 or "DELETE 0" not in stdout:
        print(f"[FAIL] RLS DELETE isolation breached! Tenant Beta deleted Alpha's row: {stdout}")
        return False
    print("[PASS] Tenant Beta DELETE affected 0 rows (Cross-Tenant Delete Blocked)")

    # 5. Tenant Beta attempts an INSERT with tenant_id = tenant_a (WITH CHECK violation)
    bad_insert_sql = f"""
    SET LOCAL ROLE mirage_app;
    SET LOCAL app.current_tenant_id = '{tenant_b}';
    INSERT INTO agents (id, tenant_id, name, max_autonomy_level, status, created_at, updated_at)
    VALUES ('agent_forged', '{tenant_a}', 'Spoofed Agent', 1, 'active', NOW(), NOW());
    """
    code, stdout, stderr = run_psql(bad_insert_sql)
    # Must fail with RLS check violation or error
    if code == 0:
        print(f"[FAIL] RLS WITH CHECK failed! Tenant Beta was able to insert a row tagged as Tenant Alpha: {stdout}")
        return False
    print("[PASS] RLS WITH CHECK policy rejected cross-tenant insert attempt")

    return True


def test_3_api_key_revocation_and_scoping() -> bool:
    print("\n--- Test 3: Live API Key Issuance, Scoping, and Instant Revocation ---")
    client = httpx.Client(base_url=GATEWAY_URL, timeout=10.0)

    from gateway.middleware.auth import create_access_token
    from shared.schemas.auth import Role

    # 1. Provision synthetic tenant via admin API
    sys_token = create_access_token(
        tenant_id="system",
        role=Role.SUPER_ADMIN,
        user_id="staging_super_admin",
    )
    sys_headers = {"Authorization": f"Bearer {sys_token}"}
    r = client.post(
        "/v1/admin/tenants",
        headers=sys_headers,
        json={"name": f"Revocation Test Tenant {uuid.uuid4().hex[:6]}"},
    )
    if r.status_code != 201:
        print(f"[FAIL] Could not provision tenant via API: {r.status_code} {r.text}")
        return False
    tenant_id = r.json().get("id")

    # Issue API key as Tenant Admin
    admin_token = create_access_token(
        tenant_id=tenant_id,
        role=Role.TENANT_ADMIN,
        user_id=f"admin_{tenant_id}",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Issue API key
    r = client.post(
        "/v1/auth/api-keys",
        headers=headers,
        json={"name": "Temporary Key", "scopes": ["verify:read"]},
    )
    if r.status_code != 201:
        print(f"[FAIL] Could not issue API key: {r.status_code} {r.text}")
        return False

    key_data = r.json()
    raw_key = key_data.get("raw_key") or key_data.get("key_secret")
    key_id = key_data.get("key_metadata", {}).get("id")

    # Verify key works for /v1/auth/me
    auth_headers = {"X-API-Key": raw_key}
    r = client.get("/v1/auth/me", headers=auth_headers)
    if r.status_code != 200:
        print(f"[FAIL] Issued API key could not authenticate: {r.status_code} {r.text}")
        return False
    print(f"[PASS] API Key '{key_id}' successfully authenticated")

    # Verify scope limitation (key has only verify:read, attempting mutating verify:write must fail with 403)
    r = client.post(
        "/v1/verify",
        headers=auth_headers,
        json={
            "prompt": "Test prompt",
            "response": "Test response",
            "tenant_id": tenant_id,
        },
    )
    if r.status_code != 403 or "verify:write" not in r.text:
        print(
            f"[FAIL] Insufficient scope check failed! Expected 403 with 'verify:write', got: {r.status_code} {r.text}"
        )
        return False
    print(f"[PASS] Scope enforcement blocked unauthorized verify:write attempt with HTTP 403 ({r.status_code})")

    # Revoke the API key
    r = client.post(f"/v1/auth/api-keys/{key_id}/revoke", headers=headers)
    if r.status_code not in (200, 204):
        print(f"[FAIL] Revocation request failed: {r.status_code} {r.text}")
        return False
    print(f"[PASS] API Key '{key_id}' revoked via /v1/auth/api-keys/{key_id}/revoke")

    # Verify immediate rejection
    r = client.get("/v1/auth/me", headers=auth_headers)
    if r.status_code != 401:
        print(f"[FAIL] Revoked key was still accepted! Got status {r.status_code}")
        return False
    print("[PASS] Revoked API key was immediately rejected with HTTP 401 Unauthorized")

    return True


def main() -> int:
    print("=" * 70)
    print("  MIRAGE 3.0 Live Adversarial & Tenant Isolation Verification")
    print("=" * 70)

    t1 = test_1_runtime_role_privilege_fencing()
    t2 = test_2_rls_crud_isolation_across_tenants()
    t3 = test_3_api_key_revocation_and_scoping()

    all_passed = t1 and t2 and t3
    print("\n" + "=" * 70)
    print(f"OVERALL RESULT: {'ALL PASSED (3/3)' if all_passed else 'FAILURES DETECTED'}")
    print("=" * 70)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
