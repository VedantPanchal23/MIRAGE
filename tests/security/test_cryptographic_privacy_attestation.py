"""Deterministic cryptographic privacy attestation verification tests for MIRAGE 3.0.

Validates that:
1. Valid Ed25519 cryptographic signatures over canonical model attributes succeed.
2. Tampered model attributes (model_id, provider, deployment_type) cause cryptographic verification failure.
3. Forged or corrupted signatures are rejected.
4. Unregistered or mismatched attestation issuers are rejected.
5. Expired or revoked attestations fail closed.
6. Malformed signature formats (non-hex, wrong length) fail closed.
7. Test keys are strictly prohibited in production mode.
8. Empty notary configuration in production strictly fails closed.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from services.model_router import model_router_service
from services.privacy_attestation import (
    create_test_notary_keypair,
    sign_model_attestation,
    verify_privacy_attestation,
)
from shared.config.settings import EnvironmentType, get_settings
from shared.schemas.model_router import (
    ModelCapabilityProfile,
    RoutingRequest,
)


@pytest.fixture
def test_notary():
    """Deterministic Ed25519 notary keypair for testing."""
    priv_key, pub_key_hex, issuer_name = create_test_notary_keypair("test-notary-crypto-v1")
    return priv_key, pub_key_hex, issuer_name


@pytest.mark.security
def test_valid_cryptographic_attestation_succeeds(test_notary) -> None:
    """Valid cryptographic signature over canonical payload verifies successfully."""
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-attested-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=now_dt,
        expires_at=expires_dt,
        issuer=issuer_name,
    )

    profile = ModelCapabilityProfile(
        model_id="mock-attested-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is True
    assert "cryptographically verified" in reason


@pytest.mark.security
def test_tampered_model_id_cryptographic_signature_rejected(test_notary) -> None:
    """Altering model_id after signing invalidates the cryptographic signature."""
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    # Signed for 'model-original'
    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="model-original",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=now_dt,
        expires_at=expires_dt,
        issuer=issuer_name,
    )

    # Presented on 'model-tampered'
    profile = ModelCapabilityProfile(
        model_id="model-tampered",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is False
    assert "Cryptographic signature verification failed" in reason


@pytest.mark.security
def test_tampered_deployment_type_rejected(test_notary) -> None:
    """Altering deployment_type from shared to dedicated causes verification failure."""
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    # Signed for 'cloud_shared'
    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_shared",
        privacy_policy_version="v1.0",
        verified_at=now_dt,
        expires_at=expires_dt,
        issuer=issuer_name,
    )

    # Claimed as 'cloud_dedicated_vpc'
    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is False
    assert "Cryptographic signature verification failed" in reason


@pytest.mark.security
def test_forged_signature_rejected(test_notary) -> None:
    """Random or inverted signature bytes are rejected."""
    _, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    forged_sig = "deadbeef" * 16  # 128 hex chars of dummy bytes

    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=forged_sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is False
    assert "Cryptographic signature verification failed" in reason


@pytest.mark.security
def test_unregistered_issuer_fails_closed(test_notary) -> None:
    """Valid signature under an unregistered issuer fails closed."""
    priv_key, _, _ = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=now_dt,
        expires_at=expires_dt,
        issuer="unknown-untrusted-notary",
    )

    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer="unknown-untrusted-notary",
        attestation_signature=sig,
    )

    # Empty trusted registry
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys={}, now=now_dt)
    assert is_valid is False
    assert "not registered in configured trusted notary registry" in reason


@pytest.mark.security
def test_expired_attestation_rejected(test_notary) -> None:
    """Expired attestation signature is rejected even if mathematically valid."""
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    verified_dt = now_dt - timedelta(days=40)
    expired_dt = now_dt - timedelta(days=10)

    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=verified_dt,
        expires_at=expired_dt,
        issuer=issuer_name,
    )

    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=verified_dt,
        privacy_attestation_expires_at=expired_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is False
    assert "privacy attestation expired" in reason.lower()


@pytest.mark.security
def test_revoked_attestation_rejected(test_notary) -> None:
    """Revoked attestation signature is rejected even if mathematically valid."""
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    verified_dt = now_dt - timedelta(days=10)
    expires_dt = now_dt + timedelta(days=20)
    revoked_dt = now_dt - timedelta(days=2)

    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=verified_dt,
        expires_at=expires_dt,
        issuer=issuer_name,
    )

    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=verified_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_attestation_revoked_at=revoked_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    trusted_keys = {issuer_name: pub_key_hex}
    is_valid, reason = verify_privacy_attestation(profile, trusted_public_keys=trusted_keys, now=now_dt)
    assert is_valid is False
    assert "privacy attestation was revoked" in reason.lower()


@pytest.mark.security
def test_malformed_signature_format_rejected(test_notary) -> None:
    """Signatures with invalid length or non-hex characters are rejected."""
    _, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)

    # Length not 128
    profile_short = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        attestation_issuer=issuer_name,
        attestation_signature="bad_short_sig",
    )
    is_valid, reason = verify_privacy_attestation(
        profile_short, trusted_public_keys={issuer_name: pub_key_hex}, now=now_dt
    )
    assert is_valid is False
    assert "malformed signature length" in reason

    # Invalid hex characters
    profile_nonhex = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        attestation_issuer=issuer_name,
        attestation_signature="z" * 128,
    )
    is_valid, reason = verify_privacy_attestation(
        profile_nonhex, trusted_public_keys={issuer_name: pub_key_hex}, now=now_dt
    )
    assert is_valid is False
    assert "invalid hex" in reason


@pytest.mark.security
def test_production_mode_strictly_rejects_test_keys(test_notary) -> None:
    """In production mode, test keys are strictly prohibited from serving as trust anchors."""
    settings = get_settings()
    priv_key, pub_key_hex, issuer_name = test_notary
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    sig = sign_model_attestation(
        private_key=priv_key,
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_policy_version="v1.0",
        verified_at=now_dt,
        expires_at=expires_dt,
        issuer=issuer_name,
    )

    profile = ModelCapabilityProfile(
        model_id="mock-model",
        provider="mock",
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=now_dt,
        privacy_attestation_expires_at=expires_dt,
        privacy_policy_version="v1.0",
        attestation_issuer=issuer_name,
        attestation_signature=sig,
    )

    # Simulate production environment
    with patch.object(settings, "environment", EnvironmentType.PRODUCTION):
        is_valid, reason = verify_privacy_attestation(
            profile,
            trusted_public_keys={issuer_name: pub_key_hex},
            now=now_dt,
        )
        assert is_valid is False
        assert "strictly prohibited in production mode" in reason


@pytest.mark.security
@pytest.mark.asyncio
async def test_production_fail_closed_routing_without_notary() -> None:
    """When running without trusted notaries configured in production, routing strictly fails closed."""
    settings = get_settings()
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        taints=["phi"],
        risk_level=1,
    )

    with (
        patch.object(settings, "environment", EnvironmentType.PRODUCTION),
        patch.object(settings, "trusted_privacy_notary_public_keys", {}),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await model_router_service.route(req)

        assert exc_info.value.status_code == 422
        assert "No feasible model satisfies assurance constraints" in str(exc_info.value.detail)
