"""External Audit Anchor Engine and Pluggable Backend Architecture.

Implements PRD FR-AUD-01 & Security §10.3:
Cryptographic checkpoint anchoring outside mutable database rows, preventing
retroactive ledger revision even by privileged database administrators.
"""

from __future__ import annotations

import abc
import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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

    @staticmethod
    def verify_anchor_with_registry(
        notary_keys: NotaryKeyRegistry,
        tenant_id: str,
        anchor: AnchorProof,
    ) -> bool:
        """Shared cryptographic signature and chained-digest check for any anchor backend."""
        if anchor.tenant_id != tenant_id:
            return False

        key_bytes = notary_keys.get_key(anchor.signer_identity)
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

        if not verify_checkpoint_signature(key_bytes, canon, anchor.signature):
            return False

        expected_chained = compute_sha256(f"anchor:{canon}:{anchor.signature}:{anchor.prev_anchor_digest}")
        legacy_digest = compute_sha256(f"anchor:{canon}:{anchor.signature}")
        return anchor.anchor_digest == expected_chained or anchor.anchor_digest == legacy_digest

    @staticmethod
    def build_signed_anchor_proof(
        notary_keys: NotaryKeyRegistry,
        tenant_id: str,
        checkpoint: CheckpointModel,
        prev_anchor_digest: str,
    ) -> AnchorProof:
        """Validate signer authorization and build a hash-chained AnchorProof."""
        key_bytes = notary_keys.get_key(checkpoint.signer_identity)
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

        anchor_digest = compute_sha256(f"anchor:{canon}:{checkpoint.signature}:{prev_anchor_digest}")
        now = datetime.now(UTC)
        return AnchorProof(
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
            prev_anchor_digest=prev_anchor_digest,
            anchor_digest=anchor_digest,
        )

    @staticmethod
    async def validate_proof_sequence(
        verify_fn: Any,
        tenant_id: str,
        proofs: list[AnchorProof],
    ) -> tuple[bool, list[str]]:
        """Verify monotonic signature & prev_anchor_digest chain across ordered AnchorProof records."""
        if not proofs:
            return True, []
        defects: list[str] = []
        expected_prev_digest = "0" * 64
        for idx, proof in enumerate(proofs):
            if not await verify_fn(tenant_id=tenant_id, anchor=proof):
                defects.append(
                    f"Anchor proof at index {idx} (seq {proof.sequence_number}, id '{proof.anchor_id}') "
                    "failed cryptographic verification"
                )
            if proof.prev_anchor_digest != ("0" * 64) or idx == 0:
                if proof.prev_anchor_digest != expected_prev_digest and idx > 0:
                    defects.append(
                        f"Anchor proof chain broken at index {idx} (sequence {proof.sequence_number}): "
                        f"expected prev_anchor_digest '{expected_prev_digest}', got '{proof.prev_anchor_digest}'"
                    )
            expected_prev_digest = proof.anchor_digest
        return len(defects) == 0, defects


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

        # Determine preceding anchor digest for immutable hash chaining
        prev_anchor_digest = "0" * 64
        if tenant_file.exists():
            try:
                with open(tenant_file, encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f if ln.strip()]
                    if lines:
                        last_proof = AnchorProof.model_validate_json(lines[-1])
                        prev_anchor_digest = last_proof.anchor_digest
            except Exception as e:
                logger.warning(
                    "Could not read previous anchor proof for chaining; defaulting to genesis",
                    tenant_id=tenant_id,
                    error=str(e),
                )

        proof = self.build_signed_anchor_proof(
            notary_keys=self.notary_keys,
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            prev_anchor_digest=prev_anchor_digest,
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
        return self.verify_anchor_with_registry(self.notary_keys, tenant_id, anchor)

    async def verify_anchor_chain(self, tenant_id: str) -> tuple[bool, list[str]]:
        """Verify the complete cryptographic hash chain of anchor proofs for a tenant."""
        tenant_file = self._get_tenant_file(tenant_id)
        if not tenant_file.exists():
            return True, []

        try:
            with open(tenant_file, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except OSError as exc:
            raise AnchorUnavailableError(f"Cannot read anchor chain for tenant '{tenant_id}': {exc}") from exc

        proofs: list[AnchorProof] = []
        for idx, line in enumerate(lines):
            try:
                proofs.append(AnchorProof.model_validate_json(line))
            except Exception as e:
                return False, [f"Anchor record at index {idx} corrupted JSON: {e}"]

        return await self.validate_proof_sequence(self.verify_anchor, tenant_id, proofs)


class S3ObjectLockAuditAnchorBackend(AuditAnchorBackend):
    """WORM-enforced Amazon S3 Object Lock Compliance Mode external anchor backend.

    Addresses RSK-ANCHOR-02 by writing signed checkpoint proofs to a remote S3 bucket
    with COMPLIANCE retention lock and MD5 integrity headers so even root DB/host
    compromise cannot retroactively rewrite anchored ledger heads.
    """

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        retention_days: int | None = None,
        notary_keys: NotaryKeyRegistry | None = None,
        s3_client: Any = None,
    ) -> None:
        settings = get_settings()
        self.bucket = (bucket or settings.audit_anchor_s3_bucket or settings.s3_bucket_name).strip()
        raw_prefix = prefix if prefix is not None else settings.audit_anchor_s3_prefix
        self.prefix = raw_prefix.strip().strip("/")
        self.retention_days = retention_days or settings.audit_anchor_retention_days
        self.notary_keys = notary_keys or NotaryKeyRegistry()
        self._s3_client = s3_client

    def _get_client(self) -> Any:
        if self._s3_client is not None:
            return self._s3_client
        if not self.bucket:
            raise AnchorUnavailableError("AUDIT_ANCHOR_S3_BUCKET is required for s3_object_lock backend")
        try:
            import importlib

            boto3 = importlib.import_module("boto3")
        except ImportError as exc:
            raise AnchorUnavailableError("boto3 package is required for S3ObjectLockAuditAnchorBackend") from exc
        settings = get_settings()
        self._s3_client = boto3.client(
            "s3",
            region_name=settings.s3_region_name,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        return self._s3_client

    @staticmethod
    def _sanitize_tenant(tenant_id: str) -> str:
        clean = "".join(c for c in tenant_id if c.isalnum() or c in ("-", "_")).strip()
        if not clean:
            raise ValueError(f"Invalid tenant_id for S3 anchor storage: '{tenant_id}'")
        return clean

    def _tenant_prefix(self, tenant_id: str) -> str:
        clean = self._sanitize_tenant(tenant_id)
        return f"{self.prefix}/{clean}/" if self.prefix else f"{clean}/"

    def _object_key(self, tenant_id: str, sequence_number: int, anchor_id: str) -> str:
        return f"{self._tenant_prefix(tenant_id)}{sequence_number:012d}_{anchor_id}.json"

    async def _list_ordered_proofs(self, tenant_id: str) -> list[AnchorProof]:
        client = self._get_client()
        prefix = self._tenant_prefix(tenant_id)
        try:
            keys: list[str] = []
            token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = client.list_objects_v2(**kwargs)
                for obj in resp.get("Contents", []):
                    key = str(obj.get("Key", ""))
                    if key.endswith(".json"):
                        keys.append(key)
                if not resp.get("IsTruncated"):
                    break
                token = resp.get("NextContinuationToken")

            proofs: list[AnchorProof] = []
            for key in sorted(keys):
                body_obj = client.get_object(Bucket=self.bucket, Key=key)
                raw = body_obj["Body"].read()
                payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                proofs.append(AnchorProof.model_validate_json(payload))
            return proofs
        except AnchorUnavailableError:
            raise
        except Exception as exc:
            raise AnchorUnavailableError(f"S3 Object Lock anchor read failed for '{tenant_id}': {exc}") from exc

    async def write_anchor(self, tenant_id: str, checkpoint: CheckpointModel) -> AnchorProof:
        """Persist checkpoint proof to S3 with Object Lock COMPLIANCE retention."""
        existing = await self._list_ordered_proofs(tenant_id)
        prev_digest = existing[-1].anchor_digest if existing else ("0" * 64)
        proof = self.build_signed_anchor_proof(
            notary_keys=self.notary_keys,
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            prev_anchor_digest=prev_digest,
        )

        body_bytes = (proof.model_dump_json() + "\n").encode("utf-8")
        content_md5 = base64.b64encode(hashlib.md5(body_bytes, usedforsecurity=False).digest()).decode("ascii")
        retain_until = datetime.now(UTC) + timedelta(days=self.retention_days)
        key = self._object_key(tenant_id, proof.sequence_number, proof.anchor_id)

        client = self._get_client()
        try:
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body_bytes,
                ContentType="application/json",
                ContentMD5=content_md5,
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retain_until,
                Metadata={
                    "tenant-id": tenant_id,
                    "sequence-number": str(proof.sequence_number),
                    "anchor-digest": proof.anchor_digest,
                },
            )
            logger.info(
                "Persisted S3 Object Lock WORM audit anchor",
                tenant_id=tenant_id,
                bucket=self.bucket,
                key=key,
                sequence_number=proof.sequence_number,
            )
            return proof
        except Exception as exc:
            raise AnchorUnavailableError(f"S3 Object Lock put_object failed for '{tenant_id}': {exc}") from exc

    async def get_latest_anchor(self, tenant_id: str) -> AnchorProof | None:
        anchors = await self.list_anchors(tenant_id=tenant_id, limit=1)
        return anchors[0] if anchors else None

    async def list_anchors(self, tenant_id: str, limit: int = 50) -> list[AnchorProof]:
        proofs = await self._list_ordered_proofs(tenant_id)
        verified: list[AnchorProof] = []
        for proof in reversed(proofs):
            if await self.verify_anchor(tenant_id=tenant_id, anchor=proof):
                verified.append(proof)
                if len(verified) >= limit:
                    break
        return verified

    async def verify_anchor(self, tenant_id: str, anchor: AnchorProof) -> bool:
        return self.verify_anchor_with_registry(self.notary_keys, tenant_id, anchor)

    async def verify_anchor_chain(self, tenant_id: str) -> tuple[bool, list[str]]:
        try:
            proofs = await self._list_ordered_proofs(tenant_id)
        except Exception as exc:
            return False, [f"Failed retrieving S3 anchor chain: {exc}"]
        return await self.validate_proof_sequence(self.verify_anchor, tenant_id, proofs)


# Default singleton instances
default_anchor_backend: AuditAnchorBackend = FileAuditAnchorBackend()


def get_anchor_backend() -> AuditAnchorBackend:
    """Retrieve the authoritative external audit anchor backend based on configuration."""
    settings = get_settings()
    if getattr(settings, "audit_anchor_backend", "file") == "s3_object_lock":
        return S3ObjectLockAuditAnchorBackend()
    return default_anchor_backend
