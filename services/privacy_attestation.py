"""Authoritative Cryptographic Privacy Attestation Verification for MIRAGE 3.0 Execution Plane.

Enforces cryptographic verification of zero-data-retention and deployment privacy
claims against configured trusted notary public keys using Ed25519 digital signatures.

Signed Evidence Invariants:
1. Canonical payload binds model_id, provider, is_zero_retention, deployment_type,
   privacy_policy_version, verified_at, expires_at, and issuer.
2. Signatures must be valid 64-byte Ed25519 signatures (128 hex characters).
3. Public keys must be valid 32-byte Ed25519 public keys (64 hex characters) registered
   in settings.trusted_privacy_notary_public_keys.
4. Test-only keys (prefixed with 'test-') are strictly rejected in production environments.
5. In production environments without configured trusted notaries, sensitive-model routing
   fails closed immediately.
"""

import json
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from shared.config.settings import EnvironmentType, get_settings
from shared.schemas.model_router import ModelCapabilityProfile


def compute_canonical_attestation_bytes(
    model_id: str,
    provider: str,
    is_zero_retention: bool,
    deployment_type: str,
    privacy_policy_version: str | None,
    verified_at: datetime,
    expires_at: datetime | None,
    issuer: str,
) -> bytes:
    """Generate deterministic canonical JSON bytes representing the signed privacy attestation."""
    payload: dict[str, Any] = {
        "deployment_type": deployment_type,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "is_zero_retention": bool(is_zero_retention),
        "issuer": issuer.strip(),
        "model_id": model_id.strip(),
        "privacy_policy_version": privacy_policy_version.strip() if privacy_policy_version else None,
        "provider": provider.strip(),
        "verified_at": verified_at.isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_model_attestation(
    private_key: ed25519.Ed25519PrivateKey,
    model_id: str,
    provider: str,
    is_zero_retention: bool,
    deployment_type: str,
    privacy_policy_version: str | None,
    verified_at: datetime,
    expires_at: datetime | None,
    issuer: str,
) -> str:
    """Sign canonical model attestation payload with an Ed25519 private key, returning hex signature."""
    payload_bytes = compute_canonical_attestation_bytes(
        model_id=model_id,
        provider=provider,
        is_zero_retention=is_zero_retention,
        deployment_type=deployment_type,
        privacy_policy_version=privacy_policy_version,
        verified_at=verified_at,
        expires_at=expires_at,
        issuer=issuer,
    )
    sig_bytes = private_key.sign(payload_bytes)
    return sig_bytes.hex()


def create_test_notary_keypair(
    issuer_name: str = "test-notary-v1",
) -> tuple[ed25519.Ed25519PrivateKey, str, str]:
    """Generate a test-only Ed25519 key pair for deterministic security and unit tests."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_bytes = priv_key.public_key().public_bytes_raw()
    return priv_key, pub_key_bytes.hex(), issuer_name


def verify_privacy_attestation(
    profile: ModelCapabilityProfile,
    trusted_public_keys: dict[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Verify cryptographic privacy attestation for a model capability profile.

    Returns:
        tuple[bool, str]: (is_valid, failure_or_success_reason)
    """
    settings = get_settings()
    now_dt = now or datetime.now(UTC)

    # 1. Zero retention invariant
    if not profile.is_zero_retention:
        return False, f"Model '{profile.model_id}' does not guarantee zero data retention"

    # 2. Verification timestamp invariant
    if profile.privacy_verified_at is None:
        return False, f"Model '{profile.model_id}' lacks verified privacy attestation timestamp"

    # 3. Expiration invariant
    if profile.privacy_attestation_expires_at is not None and now_dt >= profile.privacy_attestation_expires_at:
        return (
            False,
            f"Model '{profile.model_id}' privacy attestation expired at "
            f"{profile.privacy_attestation_expires_at.isoformat()}",
        )

    # 4. Revocation invariant
    if profile.privacy_attestation_revoked_at is not None and now_dt >= profile.privacy_attestation_revoked_at:
        return (
            False,
            f"Model '{profile.model_id}' privacy attestation was revoked at "
            f"{profile.privacy_attestation_revoked_at.isoformat()}",
        )

    # 5. Deployment isolation invariant
    if profile.deployment_type not in ("cloud_dedicated_vpc", "on_prem_local", "air_gapped"):
        return (
            False,
            f"Model '{profile.model_id}' deployment type '{profile.deployment_type}' does not provide "
            "required physical/VPC isolation for sensitive taints",
        )

    # 6. Issuer provenance invariant
    issuer = (profile.attestation_issuer or "").strip()
    if not issuer:
        return False, f"Model '{profile.model_id}' lacks trusted attestation issuer provenance"

    # 7. Signature presence and format invariant
    signature_hex = (profile.attestation_signature or "").strip()
    if not signature_hex:
        return False, f"Model '{profile.model_id}' lacks cryptographic attestation signature"

    if len(signature_hex) != 128:
        return False, f"Model '{profile.model_id}' has malformed signature length (expected 128 hex chars)"

    try:
        sig_bytes = bytes.fromhex(signature_hex)
    except ValueError:
        return False, f"Model '{profile.model_id}' has invalid hex in cryptographic signature"

    # 8. Resolve trusted public keys from parameter or settings
    active_trusted_keys = trusted_public_keys
    if active_trusted_keys is None:
        active_trusted_keys = getattr(settings, "trusted_privacy_notary_public_keys", {}) or {}

    # Reject test keys in production mode
    is_prod = settings.environment == EnvironmentType.PRODUCTION
    if is_prod and (issuer.startswith("test-") or "test" in issuer.lower()):
        return (
            False,
            f"Test notary key '{issuer}' is strictly prohibited in production mode",
        )

    # 9. Verify issuer is trusted
    if issuer not in active_trusted_keys:
        return (
            False,
            f"Attestation issuer '{issuer}' is not registered in configured trusted notary registry",
        )

    pub_key_hex = active_trusted_keys[issuer].strip()
    if len(pub_key_hex) != 64:
        return False, f"Configured public key for issuer '{issuer}' has invalid length (expected 64 hex chars)"

    try:
        pub_key_bytes = bytes.fromhex(pub_key_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
    except Exception as exc:
        return False, f"Failed to initialize Ed25519 public key for issuer '{issuer}': {exc}"

    # 10. Compute canonical payload bytes and verify signature
    payload_bytes = compute_canonical_attestation_bytes(
        model_id=profile.model_id,
        provider=profile.provider,
        is_zero_retention=profile.is_zero_retention,
        deployment_type=profile.deployment_type,
        privacy_policy_version=profile.privacy_policy_version,
        verified_at=profile.privacy_verified_at,
        expires_at=profile.privacy_attestation_expires_at,
        issuer=issuer,
    )

    try:
        public_key.verify(sig_bytes, payload_bytes)
    except InvalidSignature:
        return (
            False,
            f"Cryptographic signature verification failed: signature does not match model '{profile.model_id}' "
            "attributes (possible tampering or forged signature)",
        )
    except Exception as exc:
        return False, f"Cryptographic verification error for model '{profile.model_id}': {exc}"

    return True, f"Attestation cryptographically verified by trusted issuer '{issuer}'"
