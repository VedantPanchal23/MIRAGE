"""Pydantic schemas and cryptographic trust engine for audit logging and checkpoints."""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, Field

_HEX_64_REGEX: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
GENESIS_ROOT_HASH: Final[str] = "0" * 64


class TrustAssuranceLevel(StrEnum):
    """Explicit cryptographic trust assurance tiers for Gate 5 root anchors.

    Governing Invariant:
    A zero hash is a chain initialization sentinel, NOT proof that any ledger state was
    externally witnessed. An externally authenticated checkpoint requires cryptographic
    provenance, sequence binding, and a verified notary signature.
    """

    GENESIS_SENTINEL = "GENESIS_SENTINEL"
    LOCAL_UNANCHORED = "LOCAL_UNANCHORED"
    EXTERNALLY_ANCHORED = "EXTERNALLY_ANCHORED"


def compute_sha256(text: str) -> str:
    """Compute SHA-256 hex digest for arbitrary input string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_valid_sha256_hex(val: Any) -> bool:
    """Check if value is a valid 64-character lowercase hexadecimal string."""
    return isinstance(val, str) and len(val) == 64 and bool(_HEX_64_REGEX.match(val))


def compute_checkpoint_canonical_string(
    tenant_id: str,
    ledger_identity: str,
    sequence_number: int,
    checkpoint_hash: str,
    issued_at_iso: str,
    signer_identity: str,
) -> str:
    """Compute deterministic canonical string for checkpoint signature validation."""
    return (
        f"{tenant_id.strip()}:{ledger_identity.strip()}:{sequence_number}:"
        f"{checkpoint_hash.strip().lower()}:{issued_at_iso.strip()}:{signer_identity.strip()}"
    )


def sign_checkpoint_payload(secret_key: bytes, canonical_string: str) -> str:
    """Compute HMAC-SHA256 signature over checkpoint canonical string."""
    return hmac.new(secret_key, canonical_string.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_checkpoint_signature(secret_key: bytes, canonical_string: str, signature: str) -> bool:
    """Cryptographically verify signature over canonical checkpoint string using constant-time comparison."""
    expected = sign_checkpoint_payload(secret_key, canonical_string)
    return hmac.compare_digest(expected.lower(), signature.strip().lower())


class CheckpointModel(BaseModel):
    """Immutable data model representing a cryptographically bound checkpoint."""

    checkpoint_id: str = Field(description="Unique checkpoint identifier (e.g., chk_...)")
    tenant_id: str = Field(description="Tenant boundary to which this checkpoint is strictly bound")
    checkpoint_hash: str = Field(description="Authoritative 64-character hex SHA-256 chain hash")
    sequence_number: int = Field(ge=0, description="Exact monotonic sequence number in tenant ledger")
    ledger_identity: str = Field(default="audit_logs", description="Target ledger/table identifier")
    signer_identity: str = Field(description="Identifier of authorized notary or signing authority")
    signature: str = Field(description="Cryptographic signature verifying checkpoint authenticity")
    trust_tier: TrustAssuranceLevel = Field(
        default=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
        description="Assurance tier of this checkpoint",
    )
    revoked: bool = Field(default=False, description="Whether this checkpoint has been revoked")
    revoked_at: datetime | None = Field(default=None, description="Timestamp of revocation")
    revoked_by: str | None = Field(default=None, description="Principal that revoked the checkpoint")
    revocation_reason: str | None = Field(default=None, description="Documented reason for revocation")
    issued_at: datetime = Field(description="Issuance timestamp of checkpoint")
    expires_at: datetime | None = Field(default=None, description="Expiration timestamp (fails closed if expired)")


class NotaryKeyRegistry:
    """Authoritative in-memory key management boundary for trusted notary signers.

    Cryptographic Trust Boundary & HMAC Limitations:
    Note: MIRAGE audit checkpoints signed via symmetric HMAC-SHA256 establish internal
    authenticity against tampering and cross-tenant forgery within the trust perimeter.
    However, symmetric keys shared between signers and verifiers provide authenticity,
    not third-party cryptographic non-repudiation (which requires asymmetric keypairs
    such as Ed25519 or ECDSA).
    """

    def __init__(
        self,
        initial_keys: dict[str, bytes] | None = None,
        allow_dev_keys: bool | None = None,
    ) -> None:
        self._keys: dict[str, bytes] = {}
        if initial_keys:
            for signer_id, key_bytes in initial_keys.items():
                self.register_key(signer_id, key_bytes)
        else:
            try:
                from shared.config import get_settings
                settings = get_settings()
                is_prod = str(getattr(settings, "environment", "")).lower() == "production"
                effective_allow = allow_dev_keys
                if effective_allow is None:
                    effective_allow = (not is_prod) and getattr(settings, "allow_dev_notary_keys", True)

                # Check if configured via notary_keys_json
                keys_json = getattr(settings, "notary_keys_json", None)
                if keys_json:
                    try:
                        parsed = json.loads(keys_json)
                        if isinstance(parsed, dict):
                            for s_id, k_val in parsed.items():
                                if isinstance(k_val, str):
                                    self.register_key(s_id, k_val.encode("utf-8"))
                    except Exception:
                        pass

                if not self._keys and effective_allow:
                    # Register default development/test notary key ONLY in non-production
                    self._keys["notary:system_primary"] = b"mirage-default-notary-secret-key-32b!"
            except Exception:
                if allow_dev_keys is True:
                    self._keys["notary:system_primary"] = b"mirage-default-notary-secret-key-32b!"

    def register_key(self, signer_identity: str, key_bytes: bytes) -> None:
        """Register or rotate a notary signing key."""
        if not signer_identity or not isinstance(signer_identity, str) or not signer_identity.strip():
            raise ValueError("signer_identity must be a non-empty string")
        if not key_bytes or not isinstance(key_bytes, bytes):
            raise ValueError("key_bytes must be non-empty bytes")
        self._keys[signer_identity.strip()] = key_bytes

    def get_key(self, signer_identity: str) -> bytes | None:
        """Fetch notary key by signer identity."""
        return self._keys.get(signer_identity.strip())

    def revoke_key(self, signer_identity: str) -> None:
        """Revoke a notary key, invalidating future signature validations under this key."""
        self._keys.pop(signer_identity.strip(), None)


class TrustedCheckpointRegistry:
    """Authenticated registry for tenant-scoped trust anchors and checkpoints.

    Governing Principles:
    1. A dictionary populated by arbitrary application code is NOT proof of external witnessing.
    2. Genesis root ('0'*64) is universally recognized as GENESIS_SENTINEL (initialization convention).
    3. Custom checkpoints require verified cryptographic signatures from an authorized notary key,
       binding tenant_id, sequence_number, ledger_identity, and issuance timestamp.
    4. Stale (expired), revoked, cross-tenant, or signature-forged checkpoints fail closed.
    5. In the absence of an external notary key or external witness, evaluations fail closed or
       return LOCAL_UNANCHORED assurance.
    """

    def __init__(
        self,
        notary_keys: NotaryKeyRegistry | None = None,
        initial_checkpoints: dict[str, set[str]] | None = None,
    ) -> None:
        self.notary_keys: NotaryKeyRegistry = notary_keys or NotaryKeyRegistry()
        self._checkpoints: dict[str, dict[str, CheckpointModel]] = {}

        if initial_checkpoints:
            for t_id, hashes in initial_checkpoints.items():
                for h in hashes:
                    self.register_checkpoint(t_id, h)

    def register_checkpoint(self, tenant_id: str, checkpoint_hash: str) -> None:
        """Register an unauthenticated local checkpoint (convenience/compat, LOCAL_UNANCHORED tier)."""
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        h = checkpoint_hash.lower().strip() if isinstance(checkpoint_hash, str) else ""
        if not is_valid_sha256_hex(h):
            raise ValueError(f"Invalid checkpoint hash format: '{checkpoint_hash}'")

        tid = tenant_id.strip()
        now = datetime.now(UTC)
        canon = compute_checkpoint_canonical_string(
            tenant_id=tid,
            ledger_identity="audit_logs",
            sequence_number=0,
            checkpoint_hash=h,
            issued_at_iso=now.isoformat(),
            signer_identity="local:unauthenticated",
        )
        model = CheckpointModel(
            checkpoint_id=f"chk_local_{h[:16]}",
            tenant_id=tid,
            checkpoint_hash=h,
            sequence_number=0,
            ledger_identity="audit_logs",
            signer_identity="local:unauthenticated",
            signature=compute_sha256(canon),
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
        )
        self._checkpoints.setdefault(tid, {})[h] = model

    def register_authenticated_checkpoint(self, checkpoint: CheckpointModel) -> None:
        """Register a cryptographically authenticated checkpoint with verified notary signature.

        Fails closed on:
        - Invalid hash format
        - Missing or unauthorized notary key
        - Cryptographic signature mismatch
        - Expired checkpoint (stale)
        - Revoked status
        """
        tid = checkpoint.tenant_id.strip()
        h = checkpoint.checkpoint_hash.strip().lower()
        if not is_valid_sha256_hex(h):
            raise ValueError(f"Invalid checkpoint hash format: '{checkpoint.checkpoint_hash}'")

        if checkpoint.revoked:
            raise ValueError("Cannot register a revoked checkpoint")

        now = datetime.now(UTC)
        if checkpoint.expires_at and checkpoint.expires_at <= now:
            raise ValueError(f"Cannot register expired checkpoint: expired at {checkpoint.expires_at}")

        # Signature verification against NotaryKeyRegistry
        key_bytes = self.notary_keys.get_key(checkpoint.signer_identity)
        if not key_bytes:
            raise ValueError(
                f"Unauthorized or unknown signer_identity '{checkpoint.signer_identity}' in checkpoint registry"
            )

        canon = compute_checkpoint_canonical_string(
            tenant_id=tid,
            ledger_identity=checkpoint.ledger_identity,
            sequence_number=checkpoint.sequence_number,
            checkpoint_hash=h,
            issued_at_iso=checkpoint.issued_at.isoformat(),
            signer_identity=checkpoint.signer_identity,
        )

        if not verify_checkpoint_signature(key_bytes, canon, checkpoint.signature):
            raise ValueError("Cryptographic signature verification failed for checkpoint")

        self._checkpoints.setdefault(tid, {})[h] = checkpoint

    def revoke_checkpoint(
        self, tenant_id: str, checkpoint_hash: str, revoked_by: str = "security_admin", reason: str = "Compromised"
    ) -> bool:
        """Revoke a previously registered checkpoint for a tenant."""
        tid = tenant_id.strip()
        h = checkpoint_hash.strip().lower()
        tenant_cps = self._checkpoints.get(tid, {})
        if h in tenant_cps:
            cp = tenant_cps[h]
            updated = cp.model_copy(
                update={
                    "revoked": True,
                    "revoked_at": datetime.now(UTC),
                    "revoked_by": revoked_by,
                    "revocation_reason": reason,
                }
            )
            tenant_cps[h] = updated
            return True
        return False

    def evaluate_trust_level(
        self, tenant_id: str, root_hash: str
    ) -> tuple[bool, TrustAssuranceLevel, CheckpointModel | None]:
        """Evaluate cryptographic trust status and assurance tier for a candidate trust anchor.

        Returns:
            (is_trusted, assurance_level, checkpoint_model)
        """
        if not isinstance(root_hash, str):
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        h = root_hash.lower().strip()
        if h == GENESIS_ROOT_HASH:
            return True, TrustAssuranceLevel.GENESIS_SENTINEL, None

        if not is_valid_sha256_hex(h):
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        tid = tenant_id.strip() if isinstance(tenant_id, str) else ""
        tenant_cps = self._checkpoints.get(tid, {})
        if h not in tenant_cps:
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        cp = tenant_cps[h]
        # Check revocation
        if cp.revoked:
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        # Check expiration
        now = datetime.now(UTC)
        if cp.expires_at and cp.expires_at <= now:
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        return True, cp.trust_tier, cp

    async def evaluate_trust_level_async(
        self, tenant_id: str, root_hash: str, session: Any = None
    ) -> tuple[bool, TrustAssuranceLevel, CheckpointModel | None]:
        """Evaluate cryptographic trust status with database-backed loading and verification."""
        # 1. Fast in-memory check
        is_trusted, level, cp = self.evaluate_trust_level(tenant_id, root_hash)
        if is_trusted:
            return is_trusted, level, cp

        if not isinstance(root_hash, str):
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None
        h = root_hash.lower().strip()
        if h == GENESIS_ROOT_HASH or not is_valid_sha256_hex(h):
            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        # 2. Database-backed loading under strict tenant isolation
        if session is not None:
            tid = tenant_id.strip() if isinstance(tenant_id, str) else ""
            try:
                from sqlalchemy import select

                from db.models import AuditCheckpointRecord, AuditLogRecord

                stmt = select(AuditCheckpointRecord).where(
                    AuditCheckpointRecord.tenant_id == tid,
                    AuditCheckpointRecord.checkpoint_hash == h,
                )
                res = await session.execute(stmt)
                cp_row = res.scalar_one_or_none()
                if cp_row is not None:
                    # Check revocation
                    if cp_row.revoked:
                        return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

                    # Check expiration
                    now = datetime.now(UTC)
                    if cp_row.expires_at and cp_row.expires_at <= now:
                        return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

                    # Signature verification against NotaryKeyRegistry
                    key_bytes = self.notary_keys.get_key(cp_row.signer_identity)
                    if not key_bytes:
                        return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

                    canon = compute_checkpoint_canonical_string(
                        tenant_id=cp_row.tenant_id,
                        ledger_identity=cp_row.ledger_identity,
                        sequence_number=cp_row.sequence_number,
                        checkpoint_hash=h,
                        issued_at_iso=cp_row.issued_at.isoformat(),
                        signer_identity=cp_row.signer_identity,
                    )
                    if not verify_checkpoint_signature(key_bytes, canon, cp_row.signature):
                        return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

                    # Verify sequence binding against audit_logs
                    if cp_row.sequence_number > 0:
                        audit_stmt = select(AuditLogRecord).where(
                            AuditLogRecord.tenant_id == tid,
                            AuditLogRecord.sequence_number == cp_row.sequence_number,
                        )
                        audit_row = (await session.execute(audit_stmt)).scalar_one_or_none()
                        if not audit_row or audit_row.chain_hash != h:
                            return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

                    tier_val = (
                        TrustAssuranceLevel(cp_row.trust_tier)
                        if cp_row.trust_tier in TrustAssuranceLevel.__members__.values()
                        else TrustAssuranceLevel.EXTERNALLY_ANCHORED
                    )
                    model = CheckpointModel(
                        checkpoint_id=cp_row.id,
                        tenant_id=cp_row.tenant_id,
                        checkpoint_hash=h,
                        sequence_number=cp_row.sequence_number,
                        ledger_identity=cp_row.ledger_identity,
                        signer_identity=cp_row.signer_identity,
                        signature=cp_row.signature,
                        trust_tier=tier_val,
                        revoked=cp_row.revoked,
                        revoked_at=cp_row.revoked_at,
                        revoked_by=cp_row.revoked_by,
                        revocation_reason=cp_row.revocation_reason,
                        issued_at=cp_row.issued_at,
                        expires_at=cp_row.expires_at,
                    )
                    self._checkpoints.setdefault(tid, {})[h] = model
                    return True, tier_val, model
            except Exception:
                return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

        return False, TrustAssuranceLevel.LOCAL_UNANCHORED, None

    def is_authenticated_root(self, tenant_id: str, root_hash: str) -> bool:
        """Verify whether a root hash is an active, authenticated trust anchor for the tenant."""
        is_trusted, _, _ = self.evaluate_trust_level(tenant_id, root_hash)
        return is_trusted


class AuditLogEntry(BaseModel):
    """Immutable audit entry persisted to PostgreSQL with cryptographic hash chaining."""

    entry_id: str
    tenant_id: str
    session_id: str
    trace_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    prompt_hash: str = Field(description="SHA-256 hash of original user prompt (PII safe)")
    response_hash: str = Field(description="SHA-256 hash of raw LLM response")
    hrs_score: float = Field(ge=0.0, le=1.0)
    risk_tier: str
    claims_count: int = Field(ge=0)
    claims_summary: list[dict[str, Any]] = Field(default_factory=list)
    correction_applied: bool = False
    prev_hash: str = Field(description="Chain hash of preceding audit entry in the tenant's ledger")
    chain_hash: str = Field(description="Computed SHA-256 hash verifying integrity of this ledger record")
    sequence_number: int = Field(default=0, ge=0, description="Monotonic sequence number in tenant ledger")

    @classmethod
    def create(
        cls,
        entry_id: str,
        tenant_id: str,
        session_id: str,
        trace_id: str,
        prompt: str,
        response: str,
        hrs_score: float,
        risk_tier: str,
        claims_count: int,
        claims_summary: list[dict[str, Any]],
        correction_applied: bool,
        prev_hash: str = "0" * 64,
        sequence_number: int = 0,
    ) -> "AuditLogEntry":
        """Factory constructor that automatically computes prompt, response, and chain hashes."""
        p_hash = compute_sha256(prompt)
        r_hash = compute_sha256(response)
        now = datetime.now(UTC)

        # Hash payload components deterministically
        payload = {
            "entry_id": entry_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "timestamp": now.isoformat(),
            "prompt_hash": p_hash,
            "response_hash": r_hash,
            "hrs_score": round(hrs_score, 4),
            "risk_tier": risk_tier,
            "prev_hash": prev_hash,
            "sequence_number": sequence_number,
        }
        serialized = json.dumps(payload, sort_keys=True)
        c_hash = compute_sha256(f"{prev_hash}:{serialized}")

        return cls(
            entry_id=entry_id,
            tenant_id=tenant_id,
            session_id=session_id,
            trace_id=trace_id,
            timestamp=now,
            prompt_hash=p_hash,
            response_hash=r_hash,
            hrs_score=hrs_score,
            risk_tier=risk_tier,
            claims_count=claims_count,
            claims_summary=claims_summary,
            correction_applied=correction_applied,
            prev_hash=prev_hash,
            chain_hash=c_hash,
            sequence_number=sequence_number,
        )

    def verify_integrity(self, expected_prev_hash: str | None = None) -> bool:
        """Verify that chain_hash matches recomputed hash of entry fields."""
        if expected_prev_hash is not None and self.prev_hash != expected_prev_hash:
            return False
        payload = {
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "hrs_score": round(self.hrs_score, 4),
            "risk_tier": self.risk_tier,
            "prev_hash": self.prev_hash,
            "sequence_number": self.sequence_number,
        }
        serialized = json.dumps(payload, sort_keys=True)
        expected = compute_sha256(f"{self.prev_hash}:{serialized}")
        return self.chain_hash == expected
