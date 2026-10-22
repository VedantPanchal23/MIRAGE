"""Authoritative Audit Ledger Service with Safe Concurrency, Chain Verification, and External Anchoring.

Implements PRD FR-AUD-01..04, Security §10, and Workstream B Observability & Audit:
- Serialized, lock-fenced audit ledger appends eliminating sequence forks and race conditions.
- Deterministic, canonical SHA-256 hash chaining across all five assurance gates.
- Independent verification detecting modification, deletion, reordering, and truncation.
- External audit anchor verification detecting ledger truncation relative to signed checkpoints.
- Scoped compliance evidence bundle exports with cryptographic digests.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditCheckpointRecord, AuditLogRecord, TenantAuditLedger
from services.audit_anchor import AnchorUnavailableError, get_anchor_backend
from shared.config import EnvironmentType, get_settings
from shared.logging import get_logger
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    AnchorProof,
    AuditEvidenceBundle,
    AuditIntegrityReport,
    AuditIntegrityStatus,
    CheckpointModel,
    NotaryKeyRegistry,
    TrustAssuranceLevel,
    compute_canonical_audit_hash,
    compute_checkpoint_canonical_string,
    compute_sha256,
    sign_checkpoint_payload,
)

logger = get_logger("audit_ledger")


class AuditLedgerService:
    """Authoritative service for tamper-evident audit ledger management."""

    @classmethod
    async def append_entry(
        cls,
        session: AsyncSession,
        tenant_id: str,
        event_type: str,
        actor_identity_id: str | None = None,
        transaction_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str | None = None,
        policy_reference: str | None = None,
        capability_id: str | None = None,
        reason: str | None = None,
        prompt_hash: str | None = None,
        response_hash: str | None = None,
        hrs_score: float = 0.0,
        risk_tier: str = "LOW",
        claims_count: int = 0,
        claims_summary: list[dict[str, Any]] | None = None,
        correction_applied: bool = False,
        event_payload: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> AuditLogRecord:
        """Atomically append an audit log entry to the tenant's ledger under row lock.

        Guarantees:
        1. In PostgreSQL, uses `SELECT ... FOR UPDATE` on `tenant_audit_ledgers` to serialize concurrent writers.
        2. Sequence numbers are strictly monotonic without gaps or sequence forks.
        3. Chains cryptographically from the authoritative head_chain_hash.
        4. Computes deterministic canonical SHA-256 hash.
        """
        now = created_at or datetime.now(UTC)
        settings = get_settings()
        bind = session.bind
        url_str = ""
        if bind is not None:
            if hasattr(bind, "url"):
                url_str = str(getattr(bind, "url", ""))
            elif hasattr(bind, "engine"):
                url_str = str(getattr(bind.engine, "url", ""))
        is_postgres = (
            "postgresql" in url_str and getattr(settings, "environment", EnvironmentType.TEST) != EnvironmentType.TEST
        )

        # 1. Ensure tenant audit ledger head exists
        await session.execute(
            text(
                """
                INSERT INTO tenant_audit_ledgers (
                    tenant_id, head_chain_hash, sequence_number, created_at, updated_at
                )
                VALUES (:tenant_id, :genesis_hash, 0, :now, :now)
                ON CONFLICT (tenant_id) DO NOTHING
                """
            ),
            {"tenant_id": tenant_id, "genesis_hash": GENESIS_ROOT_HASH, "now": now},
        )

        # 2. Lock the ledger row
        ledger_stmt = select(TenantAuditLedger).where(TenantAuditLedger.tenant_id == tenant_id)
        if is_postgres:
            ledger_stmt = ledger_stmt.with_for_update()

        ledger_head_row = (await session.execute(ledger_stmt)).scalar_one_or_none()

        if ledger_head_row is not None:
            prev_hash = ledger_head_row.head_chain_hash or GENESIS_ROOT_HASH
            new_seq = (ledger_head_row.sequence_number or 0) + 1
        else:
            # Fallback for mock/sqlite environments without tenant_audit_ledgers row
            latest_audit_stmt = (
                select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
                .where(AuditLogRecord.tenant_id == tenant_id)
                .order_by(AuditLogRecord.sequence_number.desc())
                .limit(1)
            )
            audit_res = await session.execute(latest_audit_stmt)
            latest_row = audit_res.first()
            prev_hash = latest_row[0] if latest_row and latest_row[0] is not None else GENESIS_ROOT_HASH
            last_seq = latest_row[1] if latest_row and len(latest_row) > 1 and latest_row[1] is not None else 0
            new_seq = last_seq + 1

        entry_id = f"aud_{time.time_ns():020d}_{uuid.uuid4().hex[:8]}"
        clean_prompt_hash = prompt_hash or compute_sha256("")
        clean_response_hash = response_hash or compute_sha256("")
        clean_session_id = session_id or (f"sess_{transaction_id}" if transaction_id else f"sess_{tenant_id}")
        clean_trace_id = trace_id or (f"trace_{transaction_id}" if transaction_id else "trace_default")

        payload_digest = compute_sha256(json.dumps(event_payload or {}, sort_keys=True)) if event_payload else ""

        chain_hash = compute_canonical_audit_hash(
            prev_hash=prev_hash,
            tenant_id=tenant_id,
            sequence_number=new_seq,
            entry_id=entry_id,
            timestamp_iso=now.isoformat(),
            event_type=event_type,
            session_id=clean_session_id,
            trace_id=clean_trace_id,
            actor_identity_id=actor_identity_id,
            transaction_id=transaction_id,
            decision=decision,
            prompt_hash=clean_prompt_hash,
            response_hash=clean_response_hash,
            hrs_score=hrs_score,
            payload_digest=payload_digest,
        )

        record = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=new_seq,
            session_id=clean_session_id,
            trace_id=clean_trace_id,
            prompt_hash=clean_prompt_hash,
            response_hash=clean_response_hash,
            hrs_score=hrs_score,
            risk_tier=risk_tier,
            claims_count=claims_count,
            claims_summary=claims_summary or [],
            correction_applied=correction_applied,
            event_type=event_type,
            actor_identity_id=actor_identity_id,
            transaction_id=transaction_id,
            decision=decision,
            policy_reference=policy_reference,
            capability_id=capability_id,
            reason=reason,
            event_payload=event_payload or {},
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(record)

        if ledger_head_row is not None:
            ledger_head_row.head_entry_id = entry_id
            ledger_head_row.head_chain_hash = chain_hash
            ledger_head_row.sequence_number = new_seq
            ledger_head_row.updated_at = now

        await session.flush()
        return record

    @classmethod
    async def verify_chain(
        cls,
        session: AsyncSession,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Cryptographically verify the entire audit log chain for a tenant.

        Detects:
        - Modification of any field included in the hash.
        - Deletion of records anywhere in the chain.
        - Reordering of records.
        - Sequence gaps or sequence forks.
        - Broken prev_hash links.
        """
        stmt = (
            select(AuditLogRecord)
            .where(AuditLogRecord.tenant_id == tenant_id)
            .order_by(AuditLogRecord.sequence_number.asc())
        )
        records = (await session.execute(stmt)).scalars().all()

        if not records:
            return {
                "valid": False,
                "tenant_id": tenant_id,
                "total_records_verified": 0,
                "chain_status": "EMPTY",
                "head_sequence": 0,
                "head_chain_hash": GENESIS_ROOT_HASH,
                "message": "No audit records found for tenant; ledger is empty.",
                "defects": ["Ledger is empty"],
            }

        defects: list[str] = []
        expected_prev_hash = GENESIS_ROOT_HASH
        expected_sequence = 1

        for idx, rec in enumerate(records):
            # 1. Monotonic sequence check
            if rec.sequence_number != expected_sequence:
                defect_msg = (
                    f"Sequence break at index {idx}: expected sequence {expected_sequence}, "
                    f"found {rec.sequence_number} (entry_id: {rec.entry_id})"
                )
                defects.append(defect_msg)
                logger.error("Audit sequence broken", tenant_id=tenant_id, defect=defect_msg)
                return {
                    "valid": False,
                    "tenant_id": tenant_id,
                    "chain_status": "TAMPERED",
                    "tampered_at_index": idx,
                    "tampered_sequence": rec.sequence_number,
                    "total_records_verified": idx,
                    "head_sequence": records[-1].sequence_number,
                    "head_chain_hash": records[-1].chain_hash,
                    "error": defect_msg,
                    "defects": defects,
                }

            # 2. Previous hash link check
            if rec.prev_hash != expected_prev_hash:
                defect_msg = (
                    f"Broken hash link at sequence {rec.sequence_number}: expected prev_hash "
                    f"'{expected_prev_hash}', found '{rec.prev_hash}' (entry_id: {rec.entry_id})"
                )
                defects.append(defect_msg)
                logger.error("Audit hash link broken", tenant_id=tenant_id, defect=defect_msg)
                return {
                    "valid": False,
                    "tenant_id": tenant_id,
                    "chain_status": "TAMPERED",
                    "tampered_at_index": idx,
                    "tampered_sequence": rec.sequence_number,
                    "total_records_verified": idx,
                    "head_sequence": records[-1].sequence_number,
                    "head_chain_hash": records[-1].chain_hash,
                    "error": defect_msg,
                    "defects": defects,
                }

            # 3. Payload integrity hash verification
            # Canonical calculation first
            payload_digest = (
                compute_sha256(json.dumps(rec.event_payload or {}, sort_keys=True)) if rec.event_payload else ""
            )
            canonical_hash = compute_canonical_audit_hash(
                prev_hash=rec.prev_hash,
                tenant_id=rec.tenant_id,
                sequence_number=rec.sequence_number,
                entry_id=rec.entry_id,
                timestamp_iso=rec.created_at.isoformat(),
                event_type=rec.event_type,
                session_id=rec.session_id,
                trace_id=rec.trace_id,
                actor_identity_id=rec.actor_identity_id,
                transaction_id=rec.transaction_id,
                decision=rec.decision,
                prompt_hash=rec.prompt_hash,
                response_hash=rec.response_hash,
                hrs_score=rec.hrs_score,
                payload_digest=payload_digest,
            )

            hash_matches = rec.chain_hash == canonical_hash

            if not hash_matches:
                # Backwards-compatibility checks for legacy format variants
                now_iso = rec.created_at.isoformat()
                legacy_sess_data = f"{rec.prev_hash}:{rec.session_id}:{rec.hrs_score:.4f}:{now_iso}"
                legacy_auth_data = f"{rec.prev_hash}:{rec.entry_id}:{rec.event_type or 'ACTION'}:{now_iso}"
                legacy_gate5_data = f"{rec.prev_hash}:{rec.entry_id}:{rec.decision or ''}:{now_iso}"
                legacy_hnd_data = f"{rec.prev_hash}:{rec.entry_id}:{rec.event_type or ''}:{now_iso}:{rec.tenant_id}"

                raw_action = rec.event_type.removeprefix("AUTH_").removeprefix("ADMIN_") if rec.event_type else ""
                legacy_api_key_data = f"{rec.prev_hash}:{rec.entry_id}:{raw_action}:{now_iso}"
                legacy_agent_data = (
                    f"{rec.prev_hash}:{rec.entry_id}:{rec.decision or ''}:{now_iso}:{rec.session_id or ''}"
                )
                legacy_action_governor_data = (
                    f"{rec.prev_hash}:{rec.entry_id}:{rec.event_type or ''}:{rec.decision or ''}:{now_iso}"
                )

                if (
                    rec.chain_hash == compute_sha256(legacy_sess_data)
                    or rec.chain_hash == compute_sha256(legacy_auth_data)
                    or rec.chain_hash == compute_sha256(legacy_gate5_data)
                    or rec.chain_hash == compute_sha256(legacy_hnd_data)
                    or rec.chain_hash == compute_sha256(legacy_api_key_data)
                    or rec.chain_hash == compute_sha256(legacy_agent_data)
                    or rec.chain_hash == compute_sha256(legacy_action_governor_data)
                ):
                    hash_matches = True

            if not hash_matches:
                defect_msg = (
                    f"Cryptographic payload hash mismatch at sequence {rec.sequence_number} "
                    f"(entry_id: {rec.entry_id}): computed '{canonical_hash}' != stored '{rec.chain_hash}'"
                )
                defects.append(defect_msg)
                logger.error("Audit payload hash mismatch", tenant_id=tenant_id, defect=defect_msg)
                return {
                    "valid": False,
                    "tenant_id": tenant_id,
                    "chain_status": "TAMPERED",
                    "tampered_at_index": idx,
                    "tampered_sequence": rec.sequence_number,
                    "total_records_verified": idx,
                    "head_sequence": records[-1].sequence_number,
                    "head_chain_hash": records[-1].chain_hash,
                    "error": defect_msg,
                    "defects": defects,
                }

            expected_prev_hash = rec.chain_hash
            expected_sequence += 1

        return {
            "valid": True,
            "tenant_id": tenant_id,
            "total_records_verified": len(records),
            "chain_status": "VERIFIED_UNBROKEN",
            "head_sequence": records[-1].sequence_number,
            "head_chain_hash": records[-1].chain_hash,
            "defects": [],
            "message": f"Successfully verified {len(records)} audit records with 0 defects.",
        }

    @classmethod
    async def verify_with_anchor(
        cls,
        session: AsyncSession,
        tenant_id: str,
    ) -> AuditIntegrityReport:
        """Verify the internal audit chain and cross-validate against the external anchor backend."""
        chain_res = await cls.verify_chain(session, tenant_id)
        is_chain_valid = chain_res.get("valid", False)
        head_sequence = int(chain_res.get("head_sequence", 0))
        head_chain_hash = str(chain_res.get("head_chain_hash", GENESIS_ROOT_HASH))
        defects = list(chain_res.get("defects", []))

        if not is_chain_valid:
            return AuditIntegrityReport(
                tenant_id=tenant_id,
                status=AuditIntegrityStatus.INTEGRITY_FAILURE,
                chain_valid=False,
                total_records=int(chain_res.get("total_records_verified", 0)),
                head_sequence=head_sequence,
                head_chain_hash=head_chain_hash,
                latest_anchor=None,
                defects=defects,
            )

        # Query external anchor
        anchor_backend = get_anchor_backend()
        try:
            latest_anchor = await anchor_backend.get_latest_anchor(tenant_id)
        except AnchorUnavailableError as exc:
            logger.warning("External audit anchor backend unavailable", tenant_id=tenant_id, error=str(exc))
            return AuditIntegrityReport(
                tenant_id=tenant_id,
                status=AuditIntegrityStatus.ANCHOR_UNAVAILABLE,
                chain_valid=True,
                total_records=int(chain_res.get("total_records_verified", 0)),
                head_sequence=head_sequence,
                head_chain_hash=head_chain_hash,
                latest_anchor=None,
                defects=["External anchor store is temporarily unavailable"],
            )

        if latest_anchor is None:
            # Check DB checkpoints table if file anchor empty
            cp_stmt = (
                select(AuditCheckpointRecord)
                .where(AuditCheckpointRecord.tenant_id == tenant_id, AuditCheckpointRecord.revoked.is_(False))
                .order_by(AuditCheckpointRecord.sequence_number.desc())
                .limit(1)
            )
            cp_row = (await session.execute(cp_stmt)).scalar_one_or_none()
            if cp_row is not None:
                latest_anchor = AnchorProof(
                    anchor_id=cp_row.id,
                    tenant_id=cp_row.tenant_id,
                    checkpoint_hash=cp_row.checkpoint_hash,
                    sequence_number=cp_row.sequence_number,
                    ledger_identity=cp_row.ledger_identity,
                    signer_identity=cp_row.signer_identity,
                    signature=cp_row.signature,
                    trust_tier=TrustAssuranceLevel(cp_row.trust_tier),
                    issued_at=cp_row.issued_at,
                    anchored_at=cp_row.created_at,
                    anchor_digest=compute_sha256(f"db_checkpoint:{cp_row.id}:{cp_row.checkpoint_hash}"),
                )

        if latest_anchor is None:
            return AuditIntegrityReport(
                tenant_id=tenant_id,
                status=AuditIntegrityStatus.CHAIN_VALID,
                chain_valid=True,
                total_records=int(chain_res.get("total_records_verified", 0)),
                head_sequence=head_sequence,
                head_chain_hash=head_chain_hash,
                latest_anchor=None,
                defects=[],
            )

        # Cross-validate anchor sequence against database sequence
        if latest_anchor.sequence_number > head_sequence:
            defect_msg = (
                f"Ledger truncation detected: external anchor commits sequence {latest_anchor.sequence_number}, "
                f"but database ledger head is only sequence {head_sequence}"
            )
            logger.error("Audit ledger truncation detected", tenant_id=tenant_id, defect=defect_msg)
            return AuditIntegrityReport(
                tenant_id=tenant_id,
                status=AuditIntegrityStatus.INTEGRITY_FAILURE,
                chain_valid=False,
                total_records=int(chain_res.get("total_records_verified", 0)),
                head_sequence=head_sequence,
                head_chain_hash=head_chain_hash,
                latest_anchor=latest_anchor,
                defects=[defect_msg],
            )

        # Verify hash match at anchor's sequence number
        anchor_rec_stmt = select(AuditLogRecord).where(
            AuditLogRecord.tenant_id == tenant_id,
            AuditLogRecord.sequence_number == latest_anchor.sequence_number,
        )
        anchor_db_rec = (await session.execute(anchor_rec_stmt)).scalar_one_or_none()
        if anchor_db_rec is None or anchor_db_rec.chain_hash != latest_anchor.checkpoint_hash:
            defect_msg = (
                f"Ledger fork/tamper detected at sequence {latest_anchor.sequence_number}: "
                f"database chain_hash '{anchor_db_rec.chain_hash if anchor_db_rec else None}' "
                f"does not match anchor checkpoint_hash '{latest_anchor.checkpoint_hash}'"
            )
            logger.error("Audit ledger fork detected against anchor", tenant_id=tenant_id, defect=defect_msg)
            return AuditIntegrityReport(
                tenant_id=tenant_id,
                status=AuditIntegrityStatus.INTEGRITY_FAILURE,
                chain_valid=False,
                total_records=int(chain_res.get("total_records_verified", 0)),
                head_sequence=head_sequence,
                head_chain_hash=head_chain_hash,
                latest_anchor=latest_anchor,
                defects=[defect_msg],
            )

        if head_sequence == latest_anchor.sequence_number:
            status = AuditIntegrityStatus.ANCHORED
        else:
            status = AuditIntegrityStatus.ANCHOR_STALE

        return AuditIntegrityReport(
            tenant_id=tenant_id,
            status=status,
            chain_valid=True,
            total_records=int(chain_res.get("total_records_verified", 0)),
            head_sequence=head_sequence,
            head_chain_hash=head_chain_hash,
            latest_anchor=latest_anchor,
            defects=[],
        )

    @classmethod
    async def create_checkpoint_and_anchor(
        cls,
        session: AsyncSession,
        tenant_id: str,
        signer_identity: str = "notary:system_primary",
        ledger_identity: str = "audit_logs",
    ) -> tuple[CheckpointModel, AnchorProof]:
        """Generate a cryptographically signed checkpoint of current ledger head and commit external anchor."""
        # Query current ledger head
        head_stmt = select(TenantAuditLedger).where(TenantAuditLedger.tenant_id == tenant_id)
        head_row = (await session.execute(head_stmt)).scalar_one_or_none()

        if head_row is None or (head_row.sequence_number or 0) == 0:
            raise ValueError(f"Cannot anchor empty ledger for tenant '{tenant_id}'")

        notary_registry = NotaryKeyRegistry()
        key_bytes = notary_registry.get_key(signer_identity)
        if not key_bytes:
            raise ValueError(f"Unknown or unauthorized signer_identity '{signer_identity}' in notary registry")

        now = datetime.now(UTC)
        checkpoint_id = f"chk_{uuid.uuid4().hex[:12]}"
        canon = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=ledger_identity,
            sequence_number=head_row.sequence_number,
            checkpoint_hash=head_row.head_chain_hash,
            issued_at_iso=now.isoformat(),
            signer_identity=signer_identity,
        )
        sig = sign_checkpoint_payload(key_bytes, canon)

        checkpoint_model = CheckpointModel(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            checkpoint_hash=head_row.head_chain_hash,
            sequence_number=head_row.sequence_number,
            ledger_identity=ledger_identity,
            signer_identity=signer_identity,
            signature=sig,
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
        )

        # 1. Persist checkpoint in PostgreSQL
        stmt = (
            pg_insert(AuditCheckpointRecord)
            .values(
                id=checkpoint_id,
                tenant_id=tenant_id,
                checkpoint_hash=checkpoint_model.checkpoint_hash,
                sequence_number=checkpoint_model.sequence_number,
                ledger_identity=ledger_identity,
                signer_identity=signer_identity,
                signature=sig,
                trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED.value,
                revoked=False,
                issued_at=now,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "checkpoint_hash"],
                set_={
                    "sequence_number": checkpoint_model.sequence_number,
                    "signature": sig,
                    "issued_at": now,
                },
            )
        )
        await session.execute(stmt)

        # 2. Persist external anchor outside DB rows
        anchor_backend = get_anchor_backend()
        anchor_proof = await anchor_backend.write_anchor(tenant_id, checkpoint_model)

        return checkpoint_model, anchor_proof

    @classmethod
    async def query_events(
        cls,
        session: AsyncSession,
        tenant_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        event_type: str | None = None,
        action_id: str | None = None,
        transaction_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query paginated, tenant-scoped audit records with deterministic ordering."""
        bounded_limit = min(max(1, limit), 100)

        query = select(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant_id)
        count_query = select(func.count(AuditLogRecord.entry_id)).where(AuditLogRecord.tenant_id == tenant_id)

        if start_time:
            query = query.where(AuditLogRecord.created_at >= start_time)
            count_query = count_query.where(AuditLogRecord.created_at >= start_time)
        if end_time:
            query = query.where(AuditLogRecord.created_at <= end_time)
            count_query = count_query.where(AuditLogRecord.created_at <= end_time)
        if event_type:
            query = query.where(AuditLogRecord.event_type == event_type)
            count_query = count_query.where(AuditLogRecord.event_type == event_type)
        if action_id:
            query = query.where((AuditLogRecord.session_id == action_id) | (AuditLogRecord.transaction_id == action_id))
            count_query = count_query.where(
                (AuditLogRecord.session_id == action_id) | (AuditLogRecord.transaction_id == action_id)
            )
        if transaction_id:
            query = query.where(AuditLogRecord.transaction_id == transaction_id)
            count_query = count_query.where(AuditLogRecord.transaction_id == transaction_id)
        if session_id:
            query = query.where(AuditLogRecord.session_id == session_id)
            count_query = count_query.where(AuditLogRecord.session_id == session_id)

        total_count = (await session.execute(count_query)).scalar_one()

        query = query.order_by(AuditLogRecord.sequence_number.desc()).limit(bounded_limit).offset(offset)
        rows = (await session.execute(query)).scalars().all()

        events = [
            {
                "entry_id": r.entry_id,
                "sequence_number": r.sequence_number,
                "session_id": r.session_id,
                "trace_id": r.trace_id,
                "event_type": r.event_type or "VERIFICATION",
                "actor_identity_id": r.actor_identity_id,
                "transaction_id": r.transaction_id,
                "decision": r.decision,
                "policy_reference": r.policy_reference,
                "capability_id": r.capability_id,
                "reason": r.reason,
                "hrs_score": r.hrs_score,
                "risk_tier": r.risk_tier,
                "prompt_hash": r.prompt_hash,
                "response_hash": r.response_hash,
                "prev_hash": r.prev_hash,
                "chain_hash": r.chain_hash,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]

        has_more = (offset + len(events)) < total_count
        next_offset = (offset + len(events)) if has_more else None

        return {
            "tenant_id": tenant_id,
            "total_count": total_count,
            "limit": bounded_limit,
            "offset": offset,
            "next_offset": next_offset,
            "events": events,
        }

    @classmethod
    async def export_evidence_bundle(
        cls,
        session: AsyncSession,
        tenant_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        transaction_id: str | None = None,
        session_id: str | None = None,
        limit: int = 500,
    ) -> AuditEvidenceBundle:
        """Generate a cryptographically sealed compliance evidence bundle."""
        events_res = await cls.query_events(
            session=session,
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
            transaction_id=transaction_id,
            session_id=session_id,
            limit=limit,
            offset=0,
        )

        integrity_report = await cls.verify_with_anchor(session, tenant_id)

        now = datetime.now(UTC)
        bundle_id = f"bnd_{uuid.uuid4().hex[:16]}"
        time_range = {
            "start": start_time.isoformat() if start_time else None,
            "end": end_time.isoformat() if end_time else None,
        }

        bundle_payload = {
            "bundle_id": bundle_id,
            "tenant_id": tenant_id,
            "exported_at": now.isoformat(),
            "time_range": time_range,
            "event_count": len(events_res["events"]),
            "events": events_res["events"],
            "chain_verification": {
                "chain_valid": integrity_report.chain_valid,
                "status": integrity_report.status.value,
                "head_sequence": integrity_report.head_sequence,
                "head_chain_hash": integrity_report.head_chain_hash,
            },
            "latest_anchor": (
                integrity_report.latest_anchor.model_dump(mode="json") if integrity_report.latest_anchor else None
            ),
        }

        bundle_bytes = json.dumps(bundle_payload, sort_keys=True).encode("utf-8")
        bundle_digest = compute_sha256(bundle_bytes.decode("utf-8"))

        return AuditEvidenceBundle(
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            exported_at=now,
            time_range=time_range,
            event_count=len(events_res["events"]),
            events=events_res["events"],
            chain_verification=bundle_payload["chain_verification"],
            latest_anchor=bundle_payload["latest_anchor"],
            bundle_digest=bundle_digest,
        )
