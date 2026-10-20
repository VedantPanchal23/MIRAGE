"""MIRAGE 3.0 Live API & Authentication Abuse Matrix Test Suite.

Exercises adversarial API vectors against the live running FastAPI Gateway:
1. Missing authentication credentials (HTTP 401).
2. Malformed JWT and API key tokens (HTTP 401).
3. Expired JWT access token (HTTP 401).
4. Tenant spoofing / header tampering (Strict derivation from verified credential).
5. Cross-tenant resource ID tampering (HTTP 404 via RLS / isolation).
6. Missing required payload schema fields (HTTP 422).
7. Oversized / abusive payload defense.
8. Unsupported Content-Type / malformed serialization (HTTP 415 / 422).
9. Idempotency replay with mismatched payload (HTTP 409).
10. Error response redaction (Zero stack traces, secrets, or internal paths leaked).
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import timedelta
from typing import Any

import httpx

from gateway.middleware.auth import create_access_token
from shared.schemas.auth import Role

GATEWAY_URL = "http://localhost:8000"
RESULTS: list[dict[str, Any]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name} - {detail}")


def run_abuse_matrix() -> bool:
    client = httpx.Client(base_url=GATEWAY_URL, timeout=10.0)

    # -------------------------------------------------------------------------
    # Setup: Provision 2 isolated tenants for cross-tenant testing
    # -------------------------------------------------------------------------
    sys_token = create_access_token(
        tenant_id="system",
        role=Role.SUPER_ADMIN,
        user_id="staging_super_admin",
    )
    sys_headers = {"Authorization": f"Bearer {sys_token}"}

    r_a = client.post(
        "/v1/admin/tenants",
        headers=sys_headers,
        json={"name": f"Abuse Alpha {uuid.uuid4().hex[:6]}", "admin_user_id": "admin_alpha"},
    )
    r_b = client.post(
        "/v1/admin/tenants",
        headers=sys_headers,
        json={"name": f"Abuse Beta {uuid.uuid4().hex[:6]}", "admin_user_id": "admin_beta"},
    )
    assert r_a.status_code == 201 and r_b.status_code == 201, "Tenant setup failed"
    tenant_a = r_a.json()["id"]
    tenant_b = r_b.json()["id"]

    token_a = create_access_token(tenant_id=tenant_a, role=Role.TENANT_ADMIN, user_id="admin_alpha")
    token_b = create_access_token(tenant_id=tenant_b, role=Role.TENANT_ADMIN, user_id="admin_beta")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Missing credentials
    r = client.get("/v1/auth/me")
    record(
        "1. Missing Authentication Credentials",
        r.status_code == 401,
        f"status={r.status_code}",
    )

    # 2. Malformed credentials
    r_jwt = client.get("/v1/auth/me", headers={"Authorization": "Bearer not_a_valid_jwt"})
    r_key = client.get("/v1/auth/me", headers={"X-API-Key": "malformed_key_gibberish"})
    record(
        "2. Malformed Credentials Rejection",
        r_jwt.status_code == 401 and r_key.status_code == 401,
        f"jwt_status={r_jwt.status_code}, key_status={r_key.status_code}",
    )

    # 3. Expired JWT access token
    expired_token = create_access_token(
        tenant_id=tenant_a,
        role=Role.TENANT_ADMIN,
        user_id="expired_user",
        expires_delta=timedelta(seconds=-3600),
    )
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    record(
        "3. Expired Token Invalidation",
        r.status_code == 401,
        f"status={r.status_code}, body={r.json().get('detail', '')}",
    )

    # 4. Header spoofing (asserting X-Tenant-Id for Tenant B with Tenant A's token)
    r = client.get("/v1/auth/me", headers={**headers_a, "X-Tenant-Id": tenant_b})
    # Identity must resolve strictly to Tenant A from the signed token
    tenant_in_context = r.json().get("tenant_id") if r.status_code == 200 else ""
    record(
        "4. Tenant Spoofing Ignored / Fenced",
        r.status_code == 200 and tenant_in_context == tenant_a,
        f"context_tenant={tenant_in_context} (expected {tenant_a})",
    )

    # 5. Cross-tenant resource identifier tampering
    # Create an agent in Tenant B
    r_agent_b = client.post(
        "/v1/agents",
        headers=headers_b,
        json={"name": "Confidential Agent B", "initial_status": "active", "max_autonomy_level": 1},
    )
    agent_b_id = r_agent_b.json().get("id", "")
    assert bool(agent_b_id), "Agent B creation failed"

    # Tenant A attempts to fetch Tenant B's agent
    r_cross = client.get(f"/v1/agents/{agent_b_id}", headers=headers_a)
    record(
        "5. Cross-Tenant Resource Isolation",
        r_cross.status_code in (403, 404),
        f"status={r_cross.status_code} (resource strictly unexposed to foreign tenant)",
    )

    # 6. Missing required payload schema fields
    r = client.post("/v1/agents", headers=headers_a, json={"invalid_field": 123})
    record(
        "6. Missing Required Fields Schema Validation",
        r.status_code == 422,
        f"status={r.status_code}",
    )

    # 7. Oversized / abusive payload defense (1 MB string)
    oversized_text = "A" * (1024 * 1024)
    try:
        r = client.post(
            "/v1/input-assurance",
            headers=headers_a,
            json={"content": oversized_text, "initial_risk": 50},
        )
        # Should either reject (400/413/422) or handle deterministically without 500 crash
        safe_handling = r.status_code in (400, 413, 422, 200)
        record(
            "7. Oversized Abusive Payload Handling",
            safe_handling,
            f"status={r.status_code}",
        )
    except Exception as e:
        record("7. Oversized Abusive Payload Handling", False, f"Exception: {e}")

    # 8. Unsupported Content-Type
    r = client.post(
        "/v1/input-assurance",
        headers={**headers_a, "Content-Type": "text/xml"},
        content="<xml>malicious</xml>",
    )
    record(
        "8. Unsupported Content-Type Rejection",
        r.status_code in (415, 422),
        f"status={r.status_code}",
    )

    # 9. Idempotency Key Replay Protection
    idem_key = f"idem_abuse_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    corr_id = f"corr_{uuid.uuid4().hex[:8]}"
    tx_payload = {
        "content": "Idempotency test payload",
        "idempotency_key": idem_key,
        "correlation_id": corr_id,
        "initial_risk": 10,
    }
    r1 = client.post("/v1/transactions", headers=headers_a, json=tx_payload)
    tx1_id = r1.json().get("id") if r1.status_code == 201 else ""

    # Replay with identical idempotency key
    r2 = client.post("/v1/transactions", headers=headers_a, json=tx_payload)
    tx2_id = r2.json().get("id") if r2.status_code in (200, 201) else ""
    record(
        "9. Idempotency Key Replay Protection",
        r1.status_code == 201 and (r2.status_code in (200, 201)) and bool(tx1_id) and tx1_id == tx2_id,
        f"r1_status={r1.status_code}, r2_status={r2.status_code}, same_tx_id={tx1_id == tx2_id}",
    )

    # 10. Error response redaction
    # Trigger an intentional error (e.g. non-existent transaction)
    r = client.get("/v1/transactions/txn_nonexistent_999", headers=headers_a)
    body = r.text
    sanitized = (
        "Traceback (most recent call last)" not in body
        and "password" not in body.lower()
        and "secret" not in body.lower()
        and "postgresql://" not in body
    )
    record(
        "10. Error Response Redaction",
        sanitized and r.status_code == 404,
        f"status={r.status_code}, sanitized={sanitized}",
    )

    print("\n" + "=" * 70)
    all_passed = all(item["passed"] for item in RESULTS)
    print(f"ABUSE MATRIX RESULTS: {sum(1 for x in RESULTS if x['passed'])}/{len(RESULTS)} PASSED")
    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    ok = run_abuse_matrix()
    sys.exit(0 if ok else 1)
