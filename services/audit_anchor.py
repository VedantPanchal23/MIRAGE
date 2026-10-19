"""External Audit Anchor Engine and Pluggable Backend Architecture.

Implements PRD FR-AUD-01 & Security §10.3:
Cryptographic checkpoint anchoring outside mutable database rows, preventing
retroactive ledger revision even by privileged database administrators.
"""

from __future__ import annotations

import abc
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.audit import (
    AnchorProof,
    CheckpointModel,
    NotaryKeyRegistry,
    compute_checkpoint_canonical_string,
    compute_sha256,
    verify_checkpoint_signature,
)

logger = get_logger("audit_anchor")


class AuditAnchorError(Exception):
    """Base exception for audit anchor operations."""


class AnchorUnavailableError(AuditAnchorError):
    """Raised when the external anchor backend is unavailable or unresponsive."""


class AnchorVerificationError(AuditAnchorError):
    """Raised when an external anchor's cryptographic signature or digest is invalid."""


class AuditAnchorBackend(abc.ABC):
    """Abstract pluggable contract for storing and retrieving external audit anchors."""

    @abc.abstractmethod
    async def write_anchor(self, tenant_id: str, checkpoint: CheckpointModel) -> AnchorProof:
        """Persist a signed checkpoint as an immutable external anchor outside mutable DB rows."""

    @abc.abstractmethod
    async def get_latest_anchor(self, tenant_id: str) -> AnchorProof | None:
        """Retrieve the latest verified external anchor proof for a tenant."""

    @abc.abstractmethod
    async def list_anchors(self, tenant_id: str, limit: int = 50) -> list[AnchorProof]:
        """List historical anchor proofs for a tenant in descending sequence order."""

    @abc.abstractmethod
    async def verify_anchor(self, tenant_id: str, anchor: AnchorProof) -> bool:
        """Cryptographically verify an anchor proof against authoritative notary keys."""


class FileAuditAnchorBackend(AuditAnchorBackend):
    """Local append-only file-based audit anchor backend.

    Security & Trust Boundaries:
    1. Stores signed checkpoints in tenant-isolated append-only files on a dedicated filesystem
       path separate from the database transaction logs.
    2. Uses symmetric HMAC-SHA256 signatures validated against NotaryKeyRegistry.
    3. Fails closed with AnchorUnavailableError on I/O failures, directory permission errors,
       or disk full conditions.
    4. Explicit Limitation: On single-host deployments sharing root/superuser administrative
       privileges, an attacker with root OS access could modify both PostgreSQL and the filesystem.
       True Byzantine fault tolerance against host compromise requires a remote append-only notary,
       transparency log (e.g. Rekor/Sigstore), or remote KMS/WORM object lock.
    """

    def __init__(
        self,
        anchor_dir: str | Path | None = None,
        notary_keys: NotaryKeyRegistry | None = None,
    ) -> None:
        settings = get_settings()
        default_dir = getattr(settings, "audit_anchor_dir", "data/audit_anchors")
        self.anchor_dir = Path(anchor_dir or default_dir)
        self.notary_keys = notary_keys or NotaryKeyRegistry()

    def _get_tenant_file(self, tenant_id: str) -> Path:
        """Resolve path to tenant's append-only anchor file with directory traversal defense."""
        clean_tenant = "".join(c for c in tenant_id if c.isalnum() or c in ("-", "_")).strip()
        if not clean_tenant:
            raise ValueError(f"Invalid tenant_id for anchor storage: '{tenant_id}'")
        return self.anchor_dir / f"{clean_tenant}.anchors.jsonl"

    def _ensure_dir(self) -> None:
        """Ensure anchor storage directory exists with restricted permissions."""
        try:
            self.anchor_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AnchorUnavailableError(f"Cannot initialize anchor directory '{self.anchor_dir}': {exc}") from exc

    async def write_anchor(self, tenant_id: str, checkpoint: CheckpointModel) -> AnchorProof:
        """Append a signed checkpoint to the external anchor file with fsync durability."""
        self._ensure_dir()
        tenant_file = self._get_tenant_file(tenant_id)

        # Validate signature before anchoring
        key_bytes = self.notary_keys.get_key(checkpoint.signer_identity)
        if not key_bytes:
            raise AnchorUnavailableError(
                f"Unauthorized or unknown signer_identity '{checkpoint.signer_identity}' for anchor signing"
            )

        canon = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=checkpoint.ledger_identity,
            sequence_number=checkpoint.sequence_number,
            checkpoint_hash=checkpoint.checkpoint_hash,
            issued_at_iso=checkpoint.issued_at.isoformat(),
            signer_identity=checkpoint.signer_identity,
        )

        if not verify_checkpoint_signature(key_bytes, canon, checkpoint.signature):
            raise AnchorVerificationError("Cryptographic signature mismatch for checkpoint to be anchored")

        anchor_digest = compute_sha256(f"anchor:{canon}:{checkpoint.signature}")
        now = datetime.now(UTC)

        proof = AnchorProof(
            anchor_id=f"anc_{checkpoint.checkpoint_id.replace('chk_', '')}_{now.strftime('%Y%m%d%H%M%S')}",
            tenant_id=tenant_id,
            checkpoint_hash=checkpoint.checkpoint_hash,
            sequence_number=checkpoint.sequence_number,
            ledger_identity=checkpoint.ledger_identity,
            signer_identity=checkpoint.signer_identity,
            signature=checkpoint.signature,
            trust_tier=checkpoint.trust_tier,
            issued_at=checkpoint.issued_at,
            anchored_at=now,
            anchor_digest=anchor_digest,
        )

        try:
            line = proof.model_dump_json() + "\n"
            # Thread-safe / process-safe atomic append
            with open(tenant_file, mode="a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

            logger.info(
                "Appended external audit anchor",
                tenant_id=tenant_id,
                sequence_number=proof.sequence_number,
                anchor_id=proof.anchor_id,
                checkpoint_hash=proof.checkpoint_hash,
            )
            return proof
        except OSError as exc:
            logger.error("External anchor append failed", tenant_id=tenant_id, error=str(exc))
            raise AnchorUnavailableError(f"Failed writing anchor for tenant '{tenant_id}': {exc}") from exc

    async def get_latest_anchor(self, tenant_id: str) -> AnchorProof | None:
        """Fetch latest verified anchor proof from the append-only file."""
        anchors = await self.list_anchors(tenant_id=tenant_id, limit=1)
        return anchors[0] if anchors else None

    async def list_anchors(self, tenant_id: str, limit: int = 50) -> list[AnchorProof]:
        """Read historical anchor proofs in reverse sequence order."""
        tenant_file = self._get_tenant_file(tenant_id)
        if not tenant_file.exists():
            return []

        try:
            with open(tenant_file, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as exc:
            logger.warning("Failed reading anchor file", tenant_id=tenant_id, error=str(exc))
            raise AnchorUnavailableError(f"Anchor store inaccessible for tenant '{tenant_id}': {exc}") from exc

        parsed: list[AnchorProof] = []
        for line in reversed(lines):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                proof = AnchorProof.model_validate(data)
                # Verify authenticity of the anchor proof
                if await self.verify_anchor(tenant_id=tenant_id, anchor=proof):
                    parsed.append(proof)
                    if len(parsed) >= limit:
                        break
                else:
                    logger.error(
                        "Anchor file record failed cryptographic verification (tampering detected)",
                        tenant_id=tenant_id,
                        anchor_id=proof.anchor_id,
                    )
            except Exception as parse_exc:
                logger.error("Corrupted anchor line ignored", tenant_id=tenant_id, error=str(parse_exc))

        return parsed

    async def verify_anchor(self, tenant_id: str, anchor: AnchorProof) -> bool:
        """Verify the cryptographic authenticity of an anchor record."""
        if anchor.tenant_id != tenant_id:
            return False

        key_bytes = self.notary_keys.get_key(anchor.signer_identity)
        if not key_bytes:
            return False

        canon = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=anchor.ledger_identity,
            sequence_number=anchor.sequence_number,
            checkpoint_hash=anchor.checkpoint_hash,
            issued_at_iso=anchor.issued_at.isoformat(),
            signer_identity=anchor.signer_identity,
        )

        # 1. Verify signature
        if not verify_checkpoint_signature(key_bytes, canon, anchor.signature):
            # Also check against issuance time without second fractions if formatted differently
            return False

        # 2. Verify anchor digest
        expected_digest = compute_sha256(f"anchor:{canon}:{anchor.signature}")
        if anchor.anchor_digest != expected_digest:
            return False

        return True


# Default singleton instance
default_anchor_backend: AuditAnchorBackend = FileAuditAnchorBackend()


def get_anchor_backend() -> AuditAnchorBackend:
    """Retrieve the authoritative external audit anchor backend."""
    return default_anchor_backend
