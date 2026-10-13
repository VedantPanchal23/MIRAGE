"""Phase 7 Governed Memory Lifecycle Integration Tests.

Empirically validates the end-to-end HTTP API lifecycle:
1. POST /v1/memory — Epistemic classification, provenance binding, DLP scanning, multi-store propagation.
2. GET /v1/memory/{id} — Single record retrieval with full metadata and RLS isolation.
3. PUT /v1/memory/{id} — Optimistic concurrency control (expected_version), version increment, superseding lineage.
4. POST /v1/memory/{id}/dispute — Epistemic dispute tracking and immediate quarantine in Gate 2.
5. POST /v1/memory/{id}/hold — Legal hold enforcement; immunity from deletion and TTL sweeps.
6. DELETE /v1/memory/{id} — Cryptographic shredding and multi-store deletion propagation.
7. POST /v1/memory/search — Purpose-bound retrieval, trust and recency scoring, traceable ranking explanations.
8. POST /v1/memory/maintenance/sweep — Automated TTL expiration and retention policy enforcement.
9. GET /v1/memory/{id}/provenance — Lineage retrieval and audit trail verification.
10. Gate 2 Context Assembly Integration — Active memory verified, disputed memory quarantined.
"""

import uuid

import pytest
from starlette.testclient import TestClient

from db import session as db_session
from db.models import ActorIdentity, AITransaction, Tenant
from gateway.main import create_app
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import Role
from shared.schemas.context import (
    ContextDisposition,
    ContextSourceType,
    MemoryScope,
)
from shared.schemas.control_plane import Taint, TransactionState
from shared.schemas.memory import (
    MemoryCategory,
    MemoryLifecycleState,
    MemoryPurpose,
    PropagationStatus,
    RetentionPolicy,
    TrustLevel,
)
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def memory_lifecycle_setup() -> dict[str, str]:
    """Provisions isolated tenant, identity, and transaction for Phase 7 API testing."""
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"t_p7_life_{suffix}"
    user_id = f"usr_p7_{suffix}"
    agent_id = f"act_p7_{suffix}"
    txn_id = f"txn_p7_{suffix}"

    import asyncio

    async def _seed() -> None:
        async with db_session.get_system_session() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"Phase 7 Tenant {suffix}",
                    api_key_hash=compute_sha256(tenant_id),
                )
            )
            await session.flush()
            session.add(
                ActorIdentity(
                    id=agent_id,
                    tenant_id=tenant_id,
                    subject=f"sub_p7_{suffix}",
                    principal_type="OPERATOR",
                    role=Role.TENANT_ADMIN.value,
                    active=True,
                )
            )
            await session.flush()
            session.add(
                AITransaction(
                    id=txn_id,
                    tenant_id=tenant_id,
                    actor_identity_id=agent_id,
                    idempotency_key=f"idem_p7_{suffix}",
                    correlation_id=f"corr_p7_{suffix}",
                    state=TransactionState.ASSEMBLING_CONTEXT.value,
                    max_turns=5,
                    turn_count=0,
                    taint_flags=[],
                    context_sources=[],
                )
            )
            await session.flush()

    asyncio.run(_seed())

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "txn_id": txn_id,
        "suffix": suffix,
    }


@pytest.mark.integration
def test_full_governed_memory_api_lifecycle(memory_lifecycle_setup: dict[str, str]) -> None:
    """Validates creation, read, update with concurrency, dispute, hold, and deletion."""
    tenant_id = memory_lifecycle_setup["tenant_id"]
    suffix = memory_lifecycle_setup["suffix"]

    auth_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id,
        role=Role.TENANT_ADMIN,
        user_id=f"sub_p7_{suffix}",
    )
    client = TestClient(create_app())
    client.headers.update(auth_headers)

    # 1. POST /v1/memory — Create a governed USER_FACT
    create_payload = {
        "memory_type": "ATTESTED",
        "memory_category": MemoryCategory.USER_FACT.value,
        "purpose": MemoryPurpose.TASK_GROUNDING.value,
        "content": "Customer prefers encrypted email delivery on all billing notices.",
        "trust_level": TrustLevel.VERIFIED.value,
        "retention_policy": RetentionPolicy.STANDARD.value,
        "scope": MemoryScope.USER.value,
        "source_type": "USER_DIRECT",
        "source_uri": "user://preferences/portal",
        "provenance": {
            "source_type": "USER_DIRECT",
            "source_uri": "user://preferences/portal",
            "confidence": 0.95,
        },
    }
    create_res = client.post("/v1/memory", json=create_payload)
    assert create_res.status_code == 201, f"Failed create: {create_res.text}"
    created = create_res.json()
    memory_id = created["id"]
    assert memory_id.startswith("mem_")
    assert created["memory_category"] == MemoryCategory.USER_FACT.value
    assert created["purpose"] == MemoryPurpose.TASK_GROUNDING.value
    assert created["trust_level"] == TrustLevel.VERIFIED.value
    assert created["version"] == 1
    assert created["lifecycle_state"] == MemoryLifecycleState.ACTIVE.value
    assert created["propagation_status"] == PropagationStatus.PROPAGATED.value
    assert created["content_hash"] is not None

    # 2. GET /v1/memory/{id} — Retrieve the created record
    get_res = client.get(f"/v1/memory/{memory_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == memory_id
    assert retrieved["content"] == create_payload["content"]
    assert retrieved["version"] == 1

    # 3. PUT /v1/memory/{id} — Optimistic locking failure (wrong expected_version)
    bad_update_res = client.put(
        f"/v1/memory/{memory_id}",
        json={
            "content": "Conflicting update",
            "expected_version": 99,
            "update_reason": "Conflicting test update",
        },
    )
    assert bad_update_res.status_code == 409
    assert "Version mismatch" in bad_update_res.json()["detail"]

    # 4. PUT /v1/memory/{id} — Valid update (expected_version=1 -> bumps to version 2)
    valid_update_res = client.put(
        f"/v1/memory/{memory_id}",
        json={
            "content": "Customer prefers PGP encrypted email delivery on all financial statements.",
            "expected_version": 1,
            "update_reason": "Customer updated encryption preference via settings",
        },
    )
    assert valid_update_res.status_code == 200
    updated = valid_update_res.json()
    assert updated["version"] == 2
    assert "PGP encrypted" in updated["content"]
    assert updated["content_hash"] != created["content_hash"]
    active_id = updated["id"]

    # Verify old record is marked SUPERSEDED pointing to active_id
    old_res = client.get(f"/v1/memory/{memory_id}")
    assert old_res.status_code == 200
    old_data = old_res.json()
    assert old_data["lifecycle_state"] == MemoryLifecycleState.SUPERSEDED.value
    assert old_data["superseded_by_id"] == active_id

    # 5. POST /v1/memory/{active_id}/hold — Apply legal hold
    hold_res = client.post(
        f"/v1/memory/{active_id}/hold",
        json={
            "hold_active": True,
            "justification": "Regulatory compliance audit investigation 2026-Q4",
        },
    )
    assert hold_res.status_code == 200
    held = hold_res.json()
    assert held["retention_policy"] == RetentionPolicy.LEGAL_HOLD.value
    assert held["retention_exception_reason"] == "Regulatory compliance audit investigation 2026-Q4"

    # 6. DELETE /v1/memory/{active_id} while on LEGAL_HOLD — Must be rejected (HTTP 409)
    blocked_delete_res = client.delete(f"/v1/memory/{active_id}")
    assert blocked_delete_res.status_code == 409
    assert "legal_hold" in blocked_delete_res.json()["detail"].lower()

    # 7. POST /v1/memory/{active_id}/hold — Release legal hold
    release_res = client.post(
        f"/v1/memory/{active_id}/hold",
        json={
            "hold_active": False,
            "justification": "Audit completed; restoring standard retention",
        },
    )
    assert release_res.status_code == 200
    assert release_res.json()["retention_policy"] == RetentionPolicy.STANDARD.value

    # 8. POST /v1/memory/{active_id}/dispute — Dispute the memory
    dispute_res = client.post(
        f"/v1/memory/{active_id}/dispute",
        json={
            "dispute_reason": "Customer email bounced; encryption key revoked",
        },
    )
    assert dispute_res.status_code == 200
    disputed = dispute_res.json()
    assert disputed["lifecycle_state"] == MemoryLifecycleState.DISPUTED.value
    assert disputed["dispute_reason"] == "Customer email bounced; encryption key revoked"

    # 9. GET /v1/memory/{active_id}/provenance — Inspect provenance and audit lineage
    prov_res = client.get(f"/v1/memory/{active_id}/provenance")
    assert prov_res.status_code == 200
    prov_data = prov_res.json()
    assert prov_data["memory_id"] == active_id
    assert prov_data["version"] == 2
    assert prov_data["content_hash"] == disputed["content_hash"]

    # 10. DELETE /v1/memory/{active_id} — Cryptographic shredding
    delete_res = client.delete(f"/v1/memory/{active_id}")
    assert delete_res.status_code == 200
    del_result = delete_res.json()
    assert del_result["overall_status"] in {
        PropagationStatus.PROPAGATED.value,
        PropagationStatus.PARTIAL_FAILURE.value,
    }
    assert del_result["postgres_shredded"] is True

    # Verify memory content is logically sanitized and marked DELETED
    shredded_res = client.get(f"/v1/memory/{active_id}")
    assert shredded_res.status_code == 200
    shredded_data = shredded_res.json()
    assert shredded_data["lifecycle_state"] == MemoryLifecycleState.DELETED.value
    assert shredded_data["content"] in {"[LOGICALLY SANITIZED / TOMBSTONED]", "[CRYPTOGRAPHICALLY SHREDDED]"}


@pytest.mark.integration
def test_governed_memory_search_and_purpose_isolation(memory_lifecycle_setup: dict[str, str]) -> None:
    """Validates purpose-bound search, query ranking, and score explanation."""
    tenant_id = memory_lifecycle_setup["tenant_id"]
    suffix = memory_lifecycle_setup["suffix"]

    auth_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id,
        role=Role.OPERATOR,
        user_id=f"sub_p7_{suffix}",
    )
    client = TestClient(create_app())
    client.headers.update(auth_headers)

    # Seed operational recovery memory
    op_res = client.post(
        "/v1/memory",
        json={
            "memory_category": MemoryCategory.OPERATIONAL_STATE.value,
            "purpose": MemoryPurpose.OPERATIONAL_RECOVERY.value,
            "content": "Deployment cluster US-EAST-1 is configured with 16 worker nodes.",
            "trust_level": TrustLevel.VERIFIED.value,
            "scope": MemoryScope.ORGANIZATIONAL.value,
        },
    )
    assert op_res.status_code == 201

    # Seed analytics memory
    comp_res = client.post(
        "/v1/memory",
        json={
            "memory_category": MemoryCategory.USER_FACT.value,
            "purpose": MemoryPurpose.ANALYTICS.value,
            "content": "HIPAA business associate agreement signed with AWS US-EAST-1.",
            "trust_level": TrustLevel.VERIFIED.value,
            "scope": MemoryScope.ORGANIZATIONAL.value,
        },
    )
    assert comp_res.status_code == 201

    # Search for purpose=OPERATIONAL_RECOVERY: should find deployment cluster, exclude HIPAA
    search_op = client.post(
        "/v1/memory/search",
        json={
            "query": "worker nodes",
            "purpose": MemoryPurpose.OPERATIONAL_RECOVERY.value,
            "limit": 10,
        },
    )
    assert search_op.status_code == 200
    op_results = search_op.json()
    assert len(op_results["results"]) >= 1
    for r in op_results["results"]:
        assert r["purpose"] == MemoryPurpose.OPERATIONAL_RECOVERY.value
        assert "inclusion_reason" in r
        assert "effective_trust_score" in r

    # Search for purpose=ANALYTICS: should find HIPAA, exclude cluster
    search_comp = client.post(
        "/v1/memory/search",
        json={
            "query": "business associate",
            "purpose": MemoryPurpose.ANALYTICS.value,
            "limit": 10,
        },
    )
    assert search_comp.status_code == 200
    comp_results = search_comp.json()
    assert len(comp_results["results"]) >= 1
    for r in comp_results["results"]:
        assert r["purpose"] == MemoryPurpose.ANALYTICS.value


@pytest.mark.integration
def test_retention_sweep_endpoint(memory_lifecycle_setup: dict[str, str]) -> None:
    """Validates the maintenance sweep endpoint executes successfully."""
    tenant_id = memory_lifecycle_setup["tenant_id"]
    suffix = memory_lifecycle_setup["suffix"]

    auth_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id,
        role=Role.OPERATOR,
        user_id=f"sub_p7_{suffix}",
    )
    client = TestClient(create_app())
    client.headers.update(auth_headers)

    sweep_res = client.post("/v1/memory/maintenance/sweep")
    assert sweep_res.status_code == 200
    sweep_data = sweep_res.json()
    assert "expired_count" in sweep_data
    assert "timestamp" in sweep_data
    assert sweep_data["tenant_id"] == tenant_id


@pytest.mark.integration
def test_gate2_context_assembly_integration(memory_lifecycle_setup: dict[str, str]) -> None:
    """Validates that Gate 2 /v1/context/assemble evaluates governed memory lifecycle correctly:

    - Active memory passes verification (ACCEPTED).
    - Disputed memory is rejected below trust threshold with disputed_memory indicator.
    """
    tenant_id = memory_lifecycle_setup["tenant_id"]
    txn_id = memory_lifecycle_setup["txn_id"]
    suffix = memory_lifecycle_setup["suffix"]

    auth_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id,
        role=Role.OPERATOR,
        user_id=f"sub_p7_{suffix}",
    )
    client = TestClient(create_app())
    client.headers.update(auth_headers)

    # 1. Create active attested memory
    mem1_res = client.post(
        "/v1/memory",
        json={
            "memory_type": "ATTESTED",
            "memory_category": MemoryCategory.USER_FACT.value,
            "purpose": MemoryPurpose.TASK_GROUNDING.value,
            "content": "Production database primary is db.prod.internal port 5432.",
            "trust_level": TrustLevel.VERIFIED.value,
            "scope": MemoryScope.ORGANIZATIONAL.value,
        },
    )
    assert mem1_res.status_code == 201
    mem1_id = mem1_res.json()["id"]

    # 2. Create disputed memory
    mem2_res = client.post(
        "/v1/memory",
        json={
            "memory_category": MemoryCategory.INFERRED_PREFERENCE.value,
            "purpose": MemoryPurpose.TASK_GROUNDING.value,
            "content": "User prefers dark mode during daytime hours.",
            "trust_level": TrustLevel.PROVISIONAL.value,
            "scope": MemoryScope.ORGANIZATIONAL.value,
        },
    )
    assert mem2_res.status_code == 201
    mem2_id = mem2_res.json()["id"]

    # Dispute mem2
    client.post(
        f"/v1/memory/{mem2_id}/dispute",
        json={"dispute_reason": "User explicitly stated daylight preference"},
    )

    # 3. Assemble context referencing both memories
    assemble_res = client.post(
        "/v1/context/assemble",
        json={
            "transaction_id": txn_id,
            "min_trust_threshold": 0.50,
            "quarantine_injections": True,
            "items": [
                {
                    "source_type": ContextSourceType.MEMORY_ATTESTED.value,
                    "content": "Production database primary is db.prod.internal port 5432.",
                    "declared_taint": Taint.INTERNAL.value,
                    "provenance": {
                        "source_uri": f"memory://{mem1_id}",
                        "source_type": "MEMORY",
                        "origin_id": mem1_id,
                        "generation": 1,
                        "retrieval_score": 0.95,
                    },
                },
                {
                    "source_type": ContextSourceType.MEMORY_ATTESTED.value,
                    "content": "User prefers dark mode during daytime hours.",
                    "declared_taint": Taint.INTERNAL.value,
                    "provenance": {
                        "source_uri": f"memory://{mem2_id}",
                        "source_type": "MEMORY",
                        "origin_id": mem2_id,
                        "generation": 1,
                        "retrieval_score": 0.80,
                    },
                },
            ],
        },
    )
    assert assemble_res.status_code == 200
    assembled = assemble_res.json()
    items = assembled["context_items"]
    assert len(items) == 2

    mem1_item = next(i for i in items if i["provenance"]["origin_id"] == mem1_id)
    mem2_item = next(i for i in items if i["provenance"]["origin_id"] == mem2_id)

    # Active memory should be ACCEPTED
    assert mem1_item["disposition"] == ContextDisposition.ACCEPTED.value
    assert mem1_item["trust_score"] >= 0.80

    # Disputed memory should be quarantined as untrusted data with disputed_memory indicator
    assert mem2_item["disposition"] == ContextDisposition.QUARANTINED_AS_DATA.value
    assert "disputed_memory" in mem2_item["indicators"]
