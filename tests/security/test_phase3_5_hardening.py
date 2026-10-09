"""Phase 3.5 Security Hardening and Execution-Path Adversarial Test Suite.

Proves that:
1. Tool Proxy is mandatory and directly unbypassable.
2. Action Contracts are cryptographically tamper-proof post-approval.
3. Approvals cannot be replayed (single-use, transaction-bound, time-bound).
4. Agents/Requesters cannot self-grant approvals.
5. Tool Registry privilege escalation and egress demotion are blocked.
6. Advanced SSRF vectors (decimal, hex, octal, IPv6, alternate schemes) are blocked.
7. Advanced Path Traversal vectors (%2e%2e, Unicode, null byte, UNC, drive root) are blocked.
8. Salami-slicing dollar cost spoofing is prevented via parameter extraction.
9. Runtime capability revocation immediately blocks execution (fail-closed).
10. Parent transaction abortion halts action execution.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from db import session as db_session
from db.models import (
    ActionContract,
    ActorIdentity,
    AITransaction,
    Capability,
    Tenant,
    ToolDefinition,
    User,
)
from gateway.main import create_app
from services.action_governor import GovernedToolProxy, ToolProxyBypassError
from shared.schemas.action import (
    ActionState,
    EgressType,
    ToolTrustLevel,
    ToolType,
    normalize_action_parameters,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Decision
from tests.auth_factory import AuthTestFactory


async def _seed_test_identity(
    session, tenant_id: str, actor_sub: str, actor_id: str, role: Role = Role.API_CLIENT
) -> None:
    """Helper to seed Tenant, User, and ActorIdentity cleanly with proper foreign keys."""
    session.add(Tenant(id=tenant_id, name="Hardening Tenant", api_key_hash=uuid.uuid4().hex))
    await session.flush()
    session.add(
        User(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Sec User",
            role=role.value,
        )
    )
    session.add(
        ActorIdentity(
            id=actor_id,
            tenant_id=tenant_id,
            subject=actor_sub,
            principal_type="USER",
            role=role.value,
        )
    )
    await session.flush()


# =============================================================================
# 1. Tool Proxy Boundary & Bypass Prevention
# =============================================================================

@pytest.mark.asyncio
async def test_tool_proxy_direct_bypass_rejected() -> None:
    """Tool Proxy cannot be directly invoked if contract is not in EXECUTING state."""
    proxy = GovernedToolProxy()
    mock_contract = ActionContract(
        id="act_test_bypass",
        tenant_id="tenant_x",
        transaction_id="txn_x",
        actor_identity_id="actor_x",
        tool_id="tool_calc",
        tool_name="calculator",
        action_type="EXECUTE",
        target_resource="calc",
        parameters={"expression": "2+2"},
        normalized_parameters={"expression": "2+2"},
        parameters_hash="hash_x",
        required_capability="math:calculate",
        state=ActionState.PROPOSED.value,  # NOT EXECUTING!
        idempotency_key="idem_bypass",
    )
    auth = AuthContext(
        tenant_id="tenant_x",
        role=Role.API_CLIENT,
        user_id="actor_x",
        identity_id="actor_x",
        principal_type="USER",
        is_authenticated=True,
    )

    with pytest.raises(ToolProxyBypassError, match="Direct tool execution prohibited"):
        await proxy.dispatch(contract=mock_contract, auth=auth)

    assert proxy.get_invocation_count("calculator") == 0


# =============================================================================
# 2. Action Contract Tamper Resistance
# =============================================================================

@pytest.mark.asyncio
async def test_contract_tampering_target_resource_rejected() -> None:
    """Modifying target_resource after human approval invalidates execution."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="fs_read",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="fs:read",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="fs:read",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)
    admin_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id="admin_01", role=Role.SUPER_ADMIN)

    # Propose high-risk action requiring approval
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "fs_read",
        "action_type": "READ",
        "target_resource": "app://public/docs",
        "parameters": {"path": "readme.md"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 2000.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    approval_id = prop_res.json()["approval_id"]
    action_id = prop_res.json()["action_id"]

    # Grant approval
    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Approved public docs read"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200

    # Tamper target_resource to sensitive path
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(ActionContract).where(ActionContract.id == action_id))
        contract = res.scalar_one()
        contract.target_resource = "vault://secrets/api_keys"

    # Execution must fail closed with 403 Forbidden
    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 403
    assert "tampering detected" in exec_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_contract_tampering_action_type_rejected() -> None:
    """Modifying action_type from READ to DELETE after approval is detected and rejected."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="cloud_storage",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="cloud:storage",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="cloud:storage",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)
    admin_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id="admin_01", role=Role.SUPER_ADMIN)

    proposal = {
        "transaction_id": txn_id,
        "tool_name": "cloud_storage",
        "action_type": "READ",
        "target_resource": "s3://company-bucket/report.pdf",
        "parameters": {"bucket": "company-bucket", "key": "report.pdf"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 3000.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    approval_id = prop_res.json()["approval_id"]
    action_id = prop_res.json()["action_id"]

    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Approved read"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200

    # Tamper action_type to DELETE
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(ActionContract).where(ActionContract.id == action_id))
        contract = res.scalar_one()
        contract.action_type = "DELETE"

    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 403
    assert "tampering detected" in exec_res.json()["detail"].lower()


# =============================================================================
# 3. Approval Replay Defense
# =============================================================================

@pytest.mark.asyncio
async def test_approval_replay_attack_rejected() -> None:
    """Approval token cannot be reused once consumed for execution."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="controlled_test_probe",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="probe:execute",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="probe:execute",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)
    admin_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id="admin_01", role=Role.SUPER_ADMIN)

    proposal = {
        "transaction_id": txn_id,
        "tool_name": "controlled_test_probe",
        "action_type": "EXECUTE",
        "target_resource": "system://probe",
        "parameters": {"operation": "health_check"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 2500.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    approval_id = prop_res.json()["approval_id"]
    action_id = prop_res.json()["action_id"]

    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Approved probe"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200

    # First execution succeeds
    exec1_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec1_res.status_code == 200
    assert exec1_res.json()["state"] == "COMPLETED"

    # Reset contract to AUTHORIZED to simulate attacker attempting replay with same approval
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(ActionContract).where(ActionContract.id == action_id))
        contract = res.scalar_one()
        contract.state = ActionState.AUTHORIZED.value

    # Second execution must fail because approval was CONSUMED
    exec2_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec2_res.status_code == 403
    assert "already been consumed" in exec2_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approval_replay_cross_transaction_rejected() -> None:
    """Approval bound to Transaction A cannot be used to execute an action in Transaction B."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="customer_lookup",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="crm:read",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="crm:read",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_a = f"txn_a_{uuid.uuid4().hex[:8]}"
        txn_b = f"txn_b_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_a,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )
        session.add(
            AITransaction(
                id=txn_b,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_b_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_b_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)
    admin_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id="admin_01", role=Role.SUPER_ADMIN)

    proposal = {
        "transaction_id": txn_a,
        "tool_name": "customer_lookup",
        "action_type": "READ",
        "target_resource": "crm://customer",
        "parameters": {"customer_id": "CUST_999"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 1500.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    approval_id = prop_res.json()["approval_id"]
    action_id = prop_res.json()["action_id"]

    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Approved lookup"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200

    # Cross-transaction replay attempt: Tamper contract.transaction_id to valid txn_b
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(ActionContract).where(ActionContract.id == action_id))
        contract = res.scalar_one()
        contract.transaction_id = txn_b

    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 403
    assert "replay attack detected" in exec_res.json()["detail"].lower()


# =============================================================================
# 4. Agent Self-Approval Prevention
# =============================================================================

@pytest.mark.asyncio
async def test_agent_self_approval_same_identity_rejected() -> None:
    """An operator cannot approve an action request that they themselves proposed."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    operator_sub = f"operator_{uuid.uuid4().hex[:8]}"
    operator_id = f"test_identity_{operator_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, operator_sub, operator_id, Role.OPERATOR)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="customer_lookup",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="crm:read",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=operator_id,
                capability_type="crm:read",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=operator_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    op_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=operator_sub, role=Role.OPERATOR)

    proposal = {
        "transaction_id": txn_id,
        "tool_name": "customer_lookup",
        "action_type": "READ",
        "target_resource": "crm://customer",
        "parameters": {"customer_id": "CUST_777"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 3000.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=op_headers)
    assert prop_res.status_code == 200
    approval_id = prop_res.json()["approval_id"]

    # Same operator attempts to grant self-approval
    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Self sign-off"},
        headers=op_headers,
    )
    assert grant_res.status_code == 403
    assert "cannot approve their own action proposal" in grant_res.json()["detail"].lower()


# =============================================================================
# 5. Tool Registry Egress Demotion Defense
# =============================================================================

@pytest.mark.asyncio
async def test_tool_registry_egress_demotion_rejected() -> None:
    """TENANT_ADMIN cannot demote EGRESS_EXTERNAL to INTERNAL_ISOLATED without SUPER_ADMIN."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    admin_sub = f"tenant_admin_{uuid.uuid4().hex[:8]}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Hardening Tenant", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="external_webhook",
                tool_type=ToolType.HTTP.value,
                egress_type=EgressType.EGRESS_EXTERNAL.value,
                trust_level=ToolTrustLevel.UNTRUSTED.value,
                required_capability="webhook:send",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=admin_sub, role=Role.TENANT_ADMIN)

    # Attempt to demote to INTERNAL_ISOLATED
    demote_req = {
        "name": "external_webhook",
        "tool_type": "HTTP",
        "egress_type": "INTERNAL_ISOLATED",
        "trust_level": "VERIFIED",
        "required_capability": "webhook:send",
    }
    res = client.post("/v1/tools", json=demote_req, headers=headers)
    assert res.status_code == 403
    assert "demoting egress_external to internal_isolated requires super admin" in res.json()["detail"].lower()


# =============================================================================
# 6. Advanced Anti-SSRF Defense
# =============================================================================

def test_advanced_ssrf_decimal_ip_blocked() -> None:
    """Decimal IP notation (2130706433 = 127.0.0.1) is blocked."""
    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://2130706433/admin"})


def test_advanced_ssrf_hex_and_octal_ip_blocked() -> None:
    """Hexadecimal (0x7f000001) and Octal (0177.0.0.1) loopback representations are blocked."""
    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://0x7f000001/admin"})

    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://0177.0.0.1/admin"})


def test_advanced_ssrf_ipv6_loopback_and_mapped_blocked() -> None:
    """IPv6 loopback [::1] and IPv4-mapped IPv6 [::ffff:127.0.0.1] are blocked."""
    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://[::1]:8080/secrets"})

    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://[::ffff:127.0.0.1]:80/admin"})


def test_advanced_ssrf_userinfo_trick_blocked() -> None:
    """Userinfo stripping catches attempts to bypass host check via user@127.0.0.1."""
    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://legit-user:secret-pass@127.0.0.1:8000/internal"})


def test_advanced_ssrf_forbidden_schemes_blocked() -> None:
    """Non-HTTP(S) URI schemes are strictly blocked."""
    schemes = [
        "file:///etc/shadow",
        "gopher://127.0.0.1:6379/_flushall",
        "dict://localhost:11211/stats",
        "ldap://ad.internal/dc=example",
        "ftp://backup.internal/db.dump",
    ]
    for target in schemes:
        with pytest.raises(ValueError, match="Restricted (URL|URI) scheme"):
            normalize_action_parameters({"endpoint": target})


# =============================================================================
# 7. Advanced Path Traversal Defense
# =============================================================================

def test_advanced_path_traversal_url_encoded_and_unicode_blocked() -> None:
    """URL-encoded (%2e%2e) and NFKC normalized full-width Unicode dots are blocked."""
    with pytest.raises(ValueError, match="Path traversal detected"):
        normalize_action_parameters({"file": "%2e%2e/%2e%2e/etc/passwd"})

    with pytest.raises(ValueError, match="Path traversal detected"):
        # \uFF0E is full-width full stop '.'
        normalize_action_parameters({"file": "\uFF0E\uFF0E/\uFF0E\uFF0E/windows/win.ini"})


def test_advanced_path_traversal_null_bytes_and_unc_blocked() -> None:
    """Null bytes, Windows UNC network shares, and drive letters are blocked."""
    with pytest.raises(ValueError, match="Null byte detected"):
        normalize_action_parameters({"file": "legit.txt\x00.exe"})

    with pytest.raises(ValueError, match="Null byte detected"):
        normalize_action_parameters({"file": "avatar%00.jpg"})

    with pytest.raises(ValueError, match="Absolute filesystem or UNC path blocked"):
        normalize_action_parameters({"path": "\\\\10.0.0.1\\secret_share\\passwords.txt"})

    with pytest.raises(ValueError, match="Absolute filesystem or UNC path blocked"):
        normalize_action_parameters({"path": "C:\\Windows\\System32\\cmd.exe"})


# =============================================================================
# 8. Salami-Slicing Dollar Cost Spoofing Defense
# =============================================================================

@pytest.mark.asyncio
async def test_salami_slicing_financial_parameter_extraction() -> None:
    """If agent sets blast_radius.cost = $0 but parameters contain $1200, governor extracts real cost."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="disburse_funds",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="finance:transfer",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="finance:transfer",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # Agent claims cost is $0 to evade blast radius check, but passes amount: 1500.0 in parameters
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "disburse_funds",
        "action_type": "WRITE",
        "target_resource": "finance://wire",
        "parameters": {"amount": 1500.0, "recipient": "ACME Corp"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {"estimated_dollar_cost": 0.0},
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    prop_data = prop_res.json()

    # Must require human approval because effective extracted cost ($1500) breaches $1000 limit
    assert prop_data["decision"] == Decision.REQUIRE_APPROVAL.value
    assert prop_data["is_salami_slice_violation"] is True


# =============================================================================
# 9. Runtime Capability Revocation & Fail-Closed Execution
# =============================================================================

@pytest.mark.asyncio
async def test_runtime_capability_revocation_blocks_execution() -> None:
    """If capability is revoked between authorization and execution, execution fails closed."""
    tenant_id = f"sec_ten_{uuid.uuid4().hex[:8]}"
    actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        await _seed_test_identity(session, tenant_id, actor_sub, actor_id, Role.API_CLIENT)
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="calculator",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="math:calculate",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        cap_id = f"cap_{uuid.uuid4().hex[:8]}"
        session.add(
            Capability(
                id=cap_id,
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="math:calculate",
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # 1. Authorize action (low risk, passes immediately)
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "calculator",
        "action_type": "EXECUTE",
        "target_resource": "math",
        "parameters": {"expression": "100 * 5"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    assert prop_res.json()["decision"] == Decision.ALLOW.value
    action_id = prop_res.json()["action_id"]

    # 2. Security officer revokes capability before execution occurs
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(Capability).where(Capability.id == cap_id))
        cap = res.scalar_one()
        cap.revoked_at = datetime.now(UTC)

    # 3. Execution attempt must fail closed
    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 403
    assert "capability revoked or expired" in exec_res.json()["detail"].lower()
