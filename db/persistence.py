"""PostgreSQL persistence service providing atomic verification transactions and RLS queries."""

import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import AuditLogRecord, ClaimRecord, Tenant, VerificationSession
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256

logger = get_logger("postgres_persistence")


class DatabasePersistenceError(RuntimeError):
    """Base exception raised when authoritative PostgreSQL persistence operations fail."""

    pass


class DefinitivePostgresPersistenceError(DatabasePersistenceError):
    """Raised when PostgreSQL transaction definitively rolled back or failed before COMMIT.

    Guarantees no state committed to PostgreSQL. Compensating MongoDB delete is safe.
    """

    pass


class DuplicateSessionError(DefinitivePostgresPersistenceError):
    """Raised when session_id already exists in PostgreSQL (idempotent duplicate delivery)."""

    pass


class AmbiguousPostgresCommitError(DatabasePersistenceError):
    """Raised when PostgreSQL COMMIT outcome is ambiguous (e.g. connection drop during commit).

    PostgreSQL may have committed the session and audit log. Compensating MongoDB delete is UNSAFE.
    """

    pass


class PostgresPersistenceService:
    """Authoritative persistence service for verification sessions, claims, and audit logs."""

    async def ensure_tenant_exists(self, session: AsyncSession, tenant_id: str) -> None:
        """Ensure tenant row exists and lock it for audit hash-chain concurrency."""
        insert_stmt = (
            pg_insert(Tenant)
            .values(
                id=tenant_id,
                name=f"Tenant {tenant_id}",
                api_key_hash=compute_sha256(f"seed_api_key_{tenant_id}_{uuid.uuid4().hex}"),
                tier="free",
                scs_enabled=True,
                pii_detection_enabled=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(insert_stmt)

        # Explicit per-tenant serialization lock for the current transaction
        lock_stmt = select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
        await session.execute(lock_stmt)

    async def persist_verification_transaction(
        self,
        session_id: str,
        tenant_id: str,
        trace_id: str,
        model_id: str,
        prompt: str,
        response: str,
        hrs_score: float,
        risk_tier: str,
        verified_claims: list[Any],
        correction_applied: bool = False,
        timestamp: datetime | None = None,
    ) -> tuple[VerificationSession, list[ClaimRecord], AuditLogRecord]:
        """Atomically persist a verification session, all associated claims, and chained audit record.

        Guarantees:
        1. Tenant row is locked with SELECT ... FOR UPDATE to strictly serialize concurrent audit writes
           for the same tenant, preventing hash-chain branching.
        2. Pre-commit failures trigger explicit ROLLBACK and raise DefinitivePostgresPersistenceError.
        3. Commit failures raise AmbiguousPostgresCommitError to prevent unsafe compensating deletes.
        4. All operations run with transaction-local tenant context enforcing PostgreSQL RLS.
        """
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        response_hash = hashlib.sha256(response.encode("utf-8")).hexdigest()

        session = db_session.AsyncSessionLocal()
        try:
            # 1. Establish transaction-scoped tenant RLS context
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )

            # 2. Pre-Commit Phase: Lock, Inserts, Chaining, Flush
            try:
                # Lock tenant row to serialize concurrent audit writes for this tenant
                await self.ensure_tenant_exists(session, tenant_id)

                # Check if session_id already exists (idempotency guard under tenant lock)
                existing_sess = await session.get(VerificationSession, session_id)
                if existing_sess is not None:
                    await session.rollback()
                    logger.info(
                        "Session already exists in PostgreSQL under tenant lock; skipping duplicate insert",
                        session_id=session_id,
                        tenant_id=tenant_id,
                    )
                    raise DuplicateSessionError(
                        f"Session {session_id} already exists in PostgreSQL for tenant {tenant_id}"
                    )

                created_at = timestamp or datetime.now(UTC)

                # Insert VerificationSession
                sess_record = VerificationSession(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    model_id=model_id,
                    prompt_hash=prompt_hash,
                    response_hash=response_hash,
                    hrs_score=hrs_score,
                    risk_tier=risk_tier,
                    correction_applied=correction_applied,
                    created_at=created_at,
                )
                session.add(sess_record)
                await session.flush()

                # Insert ClaimRecords
                claim_records: list[ClaimRecord] = []
                claims_summary: list[dict[str, Any]] = []

                for vc in verified_claims:
                    claim_obj = getattr(vc, "claim", vc)
                    raw_id = str(getattr(claim_obj, "claim_id", getattr(vc, "id", f"c_{uuid.uuid4().hex[:8]}")))
                    c_id = f"{session_id[:24]}_{raw_id}" if not raw_id.startswith(session_id[:10]) else raw_id
                    c_text = getattr(claim_obj, "text", getattr(vc, "claim_text", ""))
                    c_type = getattr(getattr(claim_obj, "claim_type", None), "value", "factual")
                    c_crit = getattr(getattr(claim_obj, "criticality", None), "value", "medium")
                    c_weight = float(getattr(claim_obj, "criticality_weight", 0.6))
                    c_status = getattr(getattr(vc, "status", None), "value", "SUPPORTED")
                    c_risk = float(getattr(vc, "risk_score", 0.0))

                    # Signal attribution extraction
                    sig_attr: dict[str, Any] = {}
                    if hasattr(vc, "signal_scores") and isinstance(vc.signal_scores, dict):
                        sig_attr = vc.signal_scores

                    rec = ClaimRecord(
                        id=c_id,
                        session_id=session_id,
                        tenant_id=tenant_id,
                        claim_text=c_text,
                        claim_type=c_type,
                        criticality=c_crit,
                        criticality_weight=c_weight,
                        rav_score=getattr(vc, "rav_score", None),
                        scs_score=getattr(vc, "scs_score", None),
                        nli_score=getattr(vc, "nli_score", None),
                        ics_score=getattr(vc, "ics_score", None),
                        vgs_score=getattr(vc, "vgs_score", None),
                        risk_score=c_risk,
                        status=c_status,
                        signal_attribution=sig_attr,
                        created_at=created_at,
                    )
                    session.add(rec)
                    claim_records.append(rec)
                    claims_summary.append(
                        {
                            "claim_id": c_id,
                            "text": c_text[:100],
                            "status": c_status,
                            "risk_score": c_risk,
                        }
                    )

                if claim_records:
                    await session.flush()

                # Query latest audit record under exclusive tenant lock
                latest_audit_stmt = (
                    select(AuditLogRecord.chain_hash)
                    .where(AuditLogRecord.tenant_id == tenant_id)
                    .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
                    .limit(1)
                )
                audit_res = await session.execute(latest_audit_stmt)
                latest_hash = audit_res.scalar_one_or_none()
                prev_hash = latest_hash if latest_hash is not None else ("0" * 64)

                now_iso = created_at.isoformat()
                block_data = f"{prev_hash}:{session_id}:{hrs_score:.4f}:{now_iso}"
                chain_hash = compute_sha256(block_data)

                audit_entry = AuditLogRecord(
                    entry_id=f"aud_{time.time_ns():020d}_{uuid.uuid4().hex[:8]}",
                    tenant_id=tenant_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    prompt_hash=prompt_hash,
                    response_hash=response_hash,
                    hrs_score=hrs_score,
                    risk_tier=risk_tier,
                    claims_count=len(claim_records),
                    claims_summary=claims_summary,
                    correction_applied=correction_applied,
                    prev_hash=prev_hash,
                    chain_hash=chain_hash,
                    created_at=created_at,
                )
                session.add(audit_entry)
                await session.flush()

            except DuplicateSessionError:
                # Re-raise directly without wrapping into generic DefinitivePostgresPersistenceError
                raise
            except IntegrityError as integ_exc:
                await session.rollback()
                logger.warning(
                    "PostgreSQL duplicate session constraint hit; session_id already exists",
                    session_id=session_id,
                    tenant_id=tenant_id,
                    error=str(integ_exc),
                )
                raise DuplicateSessionError(
                    f"Duplicate session constraint hit for {session_id}: {integ_exc}"
                ) from integ_exc
            except Exception as pre_commit_exc:
                await session.rollback()
                logger.error(
                    "Definitive PostgreSQL failure before commit; transaction rolled back",
                    session_id=session_id,
                    tenant_id=tenant_id,
                    error=str(pre_commit_exc),
                )
                raise DefinitivePostgresPersistenceError(
                    f"Definitive PostgreSQL transaction rollback: {pre_commit_exc}"
                ) from pre_commit_exc

            # 3. Explicit Commit Phase
            try:
                await session.commit()
            except Exception as commit_exc:
                logger.error(
                    "PostgreSQL commit outcome ambiguous; network/socket failure during commit",
                    session_id=session_id,
                    tenant_id=tenant_id,
                    error=str(commit_exc),
                )
                raise AmbiguousPostgresCommitError(f"Ambiguous PostgreSQL commit outcome: {commit_exc}") from commit_exc

            logger.info(
                "Verification transaction persisted successfully to PostgreSQL",
                session_id=session_id,
                tenant_id=tenant_id,
                claims_count=len(claim_records),
                chain_hash=chain_hash,
            )
            return sess_record, claim_records, audit_entry
        finally:
            await session.close()

    async def probe_session_committed(self, tenant_id: str, session_id: str) -> bool:
        """Deterministically probe whether a session was committed to PostgreSQL after an ambiguous outcome."""
        try:
            async with db_session.get_tenant_session(tenant_id) as probe_session:
                stmt = select(VerificationSession.session_id).where(
                    VerificationSession.tenant_id == tenant_id,
                    VerificationSession.session_id == session_id,
                )
                res = await probe_session.execute(stmt)
                return res.scalar_one_or_none() is not None
        except Exception as probe_exc:
            logger.warning(
                "Probe for committed session failed",
                session_id=session_id,
                tenant_id=tenant_id,
                error=str(probe_exc),
            )
            return False

    async def get_session_by_id(self, tenant_id: str, session_id: str) -> VerificationSession | None:
        """Query verification session by ID enforcing tenant isolation."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(VerificationSession).where(
                VerificationSession.tenant_id == tenant_id,
                VerificationSession.session_id == session_id,
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    async def list_sessions(
        self,
        tenant_id: str,
        risk_tier: str | None = None,
        min_hrs: float | None = None,
        max_hrs: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Query paginated sessions from PostgreSQL with tenant RLS filtering."""
        async with db_session.get_tenant_session(tenant_id) as session:
            query = select(VerificationSession).where(VerificationSession.tenant_id == tenant_id)

            if risk_tier:
                query = query.where(VerificationSession.risk_tier == risk_tier.upper())
            if min_hrs is not None:
                query = query.where(VerificationSession.hrs_score >= min_hrs)
            if max_hrs is not None:
                query = query.where(VerificationSession.hrs_score <= max_hrs)

            # Count total matching
            count_stmt = select(func.count()).select_from(query.subquery())
            total = (await session.execute(count_stmt)).scalar() or 0

            # Fetch page
            offset = max(0, (page - 1) * page_size)
            paged_query = query.order_by(VerificationSession.created_at.desc()).offset(offset).limit(page_size)
            result = await session.execute(paged_query)
            sessions = result.scalars().all()

            items = [
                {
                    "session_id": s.session_id,
                    "tenant_id": s.tenant_id,
                    "trace_id": s.trace_id,
                    "model_id": s.model_id,
                    "prompt_hash": s.prompt_hash,
                    "response_hash": s.response_hash,
                    "hrs_score": s.hrs_score,
                    "risk_tier": s.risk_tier,
                    "correction_applied": s.correction_applied,
                    "created_at": s.created_at.isoformat() if s.created_at else "",
                }
                for s in sessions
            ]
            return total, items

    async def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """Compute aggregate statistics directly from PostgreSQL."""
        async with db_session.get_tenant_session(tenant_id) as session:
            total_stmt = select(func.count(VerificationSession.session_id)).where(
                VerificationSession.tenant_id == tenant_id
            )
            total = (await session.execute(total_stmt)).scalar() or 0

            if total == 0:
                return {
                    "total_requests": 0,
                    "average_hrs": 0.0,
                    "tier_counts": {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
                    "correction_rate": 0.0,
                }

            avg_hrs_stmt = select(func.avg(VerificationSession.hrs_score)).where(
                VerificationSession.tenant_id == tenant_id
            )
            avg_hrs = float((await session.execute(avg_hrs_stmt)).scalar() or 0.0)

            corrections_stmt = select(func.count(VerificationSession.session_id)).where(
                VerificationSession.tenant_id == tenant_id,
                VerificationSession.correction_applied.is_(True),
            )
            corrections = (await session.execute(corrections_stmt)).scalar() or 0

            tier_stmt = (
                select(VerificationSession.risk_tier, func.count(VerificationSession.session_id))
                .where(VerificationSession.tenant_id == tenant_id)
                .group_by(VerificationSession.risk_tier)
            )
            tier_rows = (await session.execute(tier_stmt)).all()
            tier_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
            for t_name, count in tier_rows:
                tier_counts[str(t_name).upper()] = count

            return {
                "total_requests": total,
                "average_hrs": round(avg_hrs, 4),
                "tier_counts": tier_counts,
                "correction_rate": round(corrections / total, 4),
            }

    async def get_time_series(self, tenant_id: str, days: int = 30) -> list[dict[str, Any]]:
        """Compute daily time-series aggregates from PostgreSQL."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(
                    func.date_trunc("day", VerificationSession.created_at).label("day"),
                    func.count(VerificationSession.session_id).label("cnt"),
                    func.avg(VerificationSession.hrs_score).label("avg_hrs"),
                )
                .where(
                    VerificationSession.tenant_id == tenant_id,
                    VerificationSession.created_at >= cutoff,
                )
                .group_by(func.date_trunc("day", VerificationSession.created_at))
                .order_by(func.date_trunc("day", VerificationSession.created_at).asc())
            )
            rows = (await session.execute(stmt)).all()

            return [
                {
                    "date": r.day.strftime("%Y-%m-%d") if r.day else "",
                    "request_count": r.cnt,
                    "average_hrs": round(float(r.avg_hrs or 0.0), 4),
                }
                for r in rows
            ]

    async def verify_audit_hash_chain(self, tenant_id: str) -> dict[str, Any]:
        """Verify the cryptographic SHA-256 hash chain from PostgreSQL records."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(AuditLogRecord)
                .where(AuditLogRecord.tenant_id == tenant_id)
                .order_by(AuditLogRecord.created_at.asc(), AuditLogRecord.entry_id.asc())
            )
            records = (await session.execute(stmt)).scalars().all()

            if not records:
                return {
                    "valid": True,
                    "tenant_id": tenant_id,
                    "total_records_verified": 0,
                    "chain_status": "EMPTY",
                    "message": "No audit records found in database for tenant.",
                }

            prev_hash = "0" * 64
            for idx, rec in enumerate(records):
                if rec.prev_hash != prev_hash:
                    return {
                        "valid": False,
                        "tenant_id": tenant_id,
                        "tampered_at_index": idx,
                        "session_id": rec.session_id,
                        "error": "Broken hash link to previous audit block",
                    }

                now_iso = rec.created_at.isoformat()
                block_data = f"{rec.prev_hash}:{rec.session_id}:{rec.hrs_score:.4f}:{now_iso}"
                expected_hash = compute_sha256(block_data)

                if rec.chain_hash != expected_hash:
                    return {
                        "valid": False,
                        "tenant_id": tenant_id,
                        "tampered_at_index": idx,
                        "session_id": rec.session_id,
                        "error": "Cryptographic payload hash mismatch (tamper detected)",
                    }
                prev_hash = rec.chain_hash

            return {
                "valid": True,
                "tenant_id": tenant_id,
                "total_records_verified": len(records),
                "chain_status": "VERIFIED_UNBROKEN",
                "chain_head": prev_hash,
                "message": f"Successfully verified {len(records)} PostgreSQL audit records with 0 defects.",
            }

    async def export_tenant_data_jsonl(self, tenant_id: str) -> list[str]:
        """Export tenant sessions in JSONL format directly from PostgreSQL."""
        import json

        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(VerificationSession)
                .where(VerificationSession.tenant_id == tenant_id)
                .order_by(VerificationSession.created_at.asc())
            )
            records = (await session.execute(stmt)).scalars().all()
            lines: list[str] = []
            for r in records:
                d = {
                    "session_id": r.session_id,
                    "tenant_id": r.tenant_id,
                    "trace_id": r.trace_id,
                    "model_id": r.model_id,
                    "prompt_hash": r.prompt_hash,
                    "response_hash": r.response_hash,
                    "hrs_score": r.hrs_score,
                    "risk_tier": r.risk_tier,
                    "correction_applied": r.correction_applied,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                lines.append(json.dumps(d))
            return lines


default_persistence_service = PostgresPersistenceService()
