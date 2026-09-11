"""Pydantic schemas for cryptographically chained audit logging."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def compute_sha256(text: str) -> str:
    """Compute SHA-256 hex digest for arbitrary input string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
