"""Pydantic schemas for cryptographically chained audit logging."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import BaseModel, Field

_HEX_64_REGEX: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
GENESIS_ROOT_HASH: Final[str] = "0" * 64


def compute_sha256(text: str) -> str:
    """Compute SHA-256 hex digest for arbitrary input string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_valid_sha256_hex(val: Any) -> bool:
    """Check if value is a valid 64-character lowercase hexadecimal string."""
    return isinstance(val, str) and len(val) == 64 and bool(_HEX_64_REGEX.match(val))


class TrustedCheckpointRegistry:
    """Authenticated registry for tenant-scoped trust anchors and checkpoints.

    Enforces that arbitrary unauthenticated caller-selected hashes cannot be
    treated as trusted roots. Checkpoints must be pre-registered per-tenant.
    The genesis root ('0' * 64) is universally authenticated by default.
    """

    def __init__(self, initial_checkpoints: dict[str, set[str]] | None = None) -> None:
        self._checkpoints: dict[str, set[str]] = {}
        if initial_checkpoints:
            for t_id, hashes in initial_checkpoints.items():
                for h in hashes:
                    self.register_checkpoint(t_id, h)

    def register_checkpoint(self, tenant_id: str, checkpoint_hash: str) -> None:
        """Register an authenticated checkpoint for a specific tenant."""
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        h = checkpoint_hash.lower().strip() if isinstance(checkpoint_hash, str) else ""
        if not is_valid_sha256_hex(h):
            raise ValueError(f"Invalid checkpoint hash format: '{checkpoint_hash}'")
        self._checkpoints.setdefault(tenant_id.strip(), set()).add(h)

    def is_authenticated_root(self, tenant_id: str, root_hash: str) -> bool:
        """Verify whether a root hash is an authenticated trust anchor for the tenant."""
        if not isinstance(root_hash, str):
            return False
        h = root_hash.lower().strip()
        if h == GENESIS_ROOT_HASH:
            return True
        if not is_valid_sha256_hex(h):
            return False
        tenant_roots = self._checkpoints.get(tenant_id.strip(), set())
        return h in tenant_roots


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
        }
        serialized = json.dumps(payload, sort_keys=True)
        expected = compute_sha256(f"{self.prev_hash}:{serialized}")
        return self.chain_hash == expected
