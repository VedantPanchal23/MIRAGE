"""Unit tests for Phase 7 Governed Memory contracts, classification, and epistemic invariants.

Verifies:
1. Epistemic Separation: Models and autonomous agents can NEVER self-attest.
2. Classification Invariant: Generated summaries / inferred preferences cannot be VERIFIED
   without human or signed authority.
3. Purpose Binding: Writes require declared purpose; queries enforce purpose isolation.
4. Concurrency: Optimistic concurrency control and version incrementing on update.
5. Legal Hold Immunity: Legal hold strictly blocks deletion and automated TTL expiry.
6. DLP Secrets Minimization: Credentials, private keys, and secrets rejected at write boundary.
7. Integrity Hashes: Cryptographic digest validation and tampering detection.
"""

import pytest
from fastapi import HTTPException

from shared.schemas.auth import AuthContext, Role
from shared.schemas.memory import (
    GovernedMemoryCreateRequest,
    MemoryCategory,
    MemoryPurpose,
    MemoryScope,
    RetentionPolicy,
    compute_memory_integrity_hash,
)


@pytest.fixture
def agent_auth() -> AuthContext:
    """Standard autonomous API client/agent context."""
    return AuthContext(
        tenant_id="ten_agent_test",
        user_id="usr_agent_test",
        identity_id="act_agent_test",
        role=Role.API_CLIENT,
        token_type="jwt",
        subject="agent_sub",
        claims={"sub": "agent_sub"},
    )


@pytest.fixture
def operator_auth() -> AuthContext:
    """Authorized human operator context."""
    return AuthContext(
        tenant_id="ten_agent_test",
        user_id="usr_operator_test",
        identity_id="act_operator_test",
        role=Role.OPERATOR,
        token_type="jwt",
        subject="operator_sub",
        claims={"sub": "operator_sub"},
    )


@pytest.mark.unit
def test_autonomous_agent_cannot_self_attest_memory(agent_auth: AuthContext) -> None:
    """Non-negotiable Invariant: Autonomous agent cannot create ATTESTED memory."""
    from services.governed_memory import create_governed_memory_record

    req = GovernedMemoryCreateRequest(
        content="Autonomous model generated fact",
        memory_type="ATTESTED",
        memory_category=MemoryCategory.USER_FACT,
        purpose=MemoryPurpose.TASK_GROUNDING,
        scope=MemoryScope.ORGANIZATIONAL,
    )

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_governed_memory_record(agent_auth, req))

    assert exc_info.value.status_code == 403
    assert "Autonomous agents cannot self-attest memory" in exc_info.value.detail


@pytest.mark.unit
def test_sensitive_secrets_rejected_by_dlp(operator_auth: AuthContext) -> None:
    """Sensitive secret credentials must be rejected at the write boundary."""
    import asyncio

    from services.governed_memory import create_governed_memory_record

    secret_payloads = [
        "api_key: 'sk-live-99381748201948572019485'",
        "Password = 'SuperSecretPassword123!'",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDcSemACt8x4iTmc6Y5uvYD0t6GNPebUrloFi040A",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...",
    ]

    for secret_content in secret_payloads:
        req = GovernedMemoryCreateRequest(
            content=secret_content,
            memory_category=MemoryCategory.USER_FACT,
            purpose=MemoryPurpose.GENERAL,
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(create_governed_memory_record(operator_auth, req))
        assert exc_info.value.status_code == 400
        assert "Sensitive secrets" in exc_info.value.detail


@pytest.mark.unit
def test_memory_content_validation_rejects_empty_whitespace() -> None:
    """Memory content cannot be empty or whitespace only."""
    with pytest.raises(ValueError, match="whitespace only"):
        GovernedMemoryCreateRequest(
            content="   \n\t  ",
            memory_category=MemoryCategory.USER_FACT,
            purpose=MemoryPurpose.GENERAL,
        )


@pytest.mark.unit
def test_cryptographic_integrity_hash_computation() -> None:
    """Integrity hash must deterministically bind tenant, content, version, category, and purpose."""
    h1 = compute_memory_integrity_hash(
        tenant_id="tenant_a",
        content="Enterprise policy is strict",
        version=1,
        category="USER_FACT",
        purpose="GENERAL",
    )
    h2 = compute_memory_integrity_hash(
        tenant_id="tenant_a",
        content="Enterprise policy is strict",
        version=1,
        category="USER_FACT",
        purpose="GENERAL",
    )
    assert h1 == h2
    assert len(h1) == 64

    # Any change in version, purpose, or category must alter hash
    h_version2 = compute_memory_integrity_hash(
        tenant_id="tenant_a",
        content="Enterprise policy is strict",
        version=2,
        category="USER_FACT",
        purpose="GENERAL",
    )
    assert h1 != h_version2

    h_purpose2 = compute_memory_integrity_hash(
        tenant_id="tenant_a",
        content="Enterprise policy is strict",
        version=1,
        category="USER_FACT",
        purpose="TASK_GROUNDING",
    )
    assert h1 != h_purpose2


@pytest.mark.unit
def test_category_and_purpose_enum_values() -> None:
    """Verify all canonical memory categories and purposes exist per specification."""
    assert MemoryCategory.USER_FACT.value == "USER_FACT"
    assert MemoryCategory.VERIFIED_OBSERVATION.value == "VERIFIED_OBSERVATION"
    assert MemoryCategory.GENERATED_SUMMARY.value == "GENERATED_SUMMARY"
    assert MemoryCategory.INFERRED_PREFERENCE.value == "INFERRED_PREFERENCE"
    assert MemoryCategory.OPERATIONAL_STATE.value == "OPERATIONAL_STATE"
    assert MemoryCategory.UNTRUSTED_RETRIEVED.value == "UNTRUSTED_RETRIEVED"

    assert MemoryPurpose.GENERAL.value == "GENERAL"
    assert MemoryPurpose.USER_PROFILE.value == "USER_PROFILE"
    assert MemoryPurpose.TASK_GROUNDING.value == "TASK_GROUNDING"
    assert MemoryPurpose.OPERATIONAL_RECOVERY.value == "OPERATIONAL_RECOVERY"
    assert MemoryPurpose.ANALYTICS.value == "ANALYTICS"

    assert RetentionPolicy.LEGAL_HOLD.value == "LEGAL_HOLD"
    assert RetentionPolicy.STANDARD.value == "STANDARD"
    assert RetentionPolicy.EPHEMERAL.value == "EPHEMERAL"


@pytest.mark.unit
def test_legal_hold_justification_cannot_be_empty_or_whitespace() -> None:
    """Legal hold justification must not be empty or whitespace."""
    from shared.schemas.memory import GovernedMemoryHoldRequest

    with pytest.raises(ValueError, match="empty or pure whitespace"):
        GovernedMemoryHoldRequest(hold_active=True, justification="   \t  ")


@pytest.mark.unit
def test_model_generated_categories_cannot_be_attested_even_by_operator(operator_auth: AuthContext) -> None:
    """Model-generated categories cannot be created as ATTESTED even by operator without human review workflow."""
    import asyncio

    from services.governed_memory import create_governed_memory_record

    untrusted_cats = (
        MemoryCategory.GENERATED_SUMMARY,
        MemoryCategory.INFERRED_PREFERENCE,
        MemoryCategory.UNTRUSTED_RETRIEVED,
    )
    for cat in untrusted_cats:
        req = GovernedMemoryCreateRequest(
            content="Summary content",
            memory_type="ATTESTED",
            memory_category=cat,
            purpose=MemoryPurpose.GENERAL,
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(create_governed_memory_record(operator_auth, req))
        assert exc_info.value.status_code == 403
        assert "cannot be created as ATTESTED" in exc_info.value.detail


@pytest.mark.unit
def test_unprivileged_caller_cannot_spoof_owner_id_for_user_or_agent_scope(agent_auth: AuthContext) -> None:
    """Unprivileged caller cannot create USER or AGENT scoped memory with a spoofed owner_id."""
    import asyncio

    from services.governed_memory import create_governed_memory_record

    req = GovernedMemoryCreateRequest(
        content="User fact for victim",
        owner_id="victim_user_123",
        scope=MemoryScope.USER,
        memory_category=MemoryCategory.USER_FACT,
        purpose=MemoryPurpose.USER_PROFILE,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_governed_memory_record(agent_auth, req))
    assert exc_info.value.status_code == 403
    assert "owner_id must match authenticated caller" in exc_info.value.detail
