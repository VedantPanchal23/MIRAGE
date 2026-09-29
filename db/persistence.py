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
from db.models import (
    AuditLogRecord,
    AuditReport,
    ClaimRecord,
    KBDocumentRecord,
    OperatorAlert,
    Tenant,
    VerificationSession,
)
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

    async def get_session_with_claims(
        self, tenant_id: str, session_id: str
    ) -> tuple[VerificationSession | None, list[ClaimRecord]]:
        """Fetch session and associated claims in a single query."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(VerificationSession).where(
                VerificationSession.tenant_id == tenant_id,
                VerificationSession.session_id == session_id,
            )
            sess = (await session.execute(stmt)).scalar_one_or_none()
            if not sess:
                return None, []

            claim_stmt = (
                select(ClaimRecord)
                .where(ClaimRecord.tenant_id == tenant_id, ClaimRecord.session_id == session_id)
                .order_by(ClaimRecord.created_at.asc())
            )
            claims = (await session.execute(claim_stmt)).scalars().all()
            return sess, list(claims)

    async def create_alert(
        self,
        tenant_id: str,
        alert_type: str,
        severity: str,
        title: str,
        description: str,
        threshold: float | None = None,
        current_value: float | None = None,
    ) -> OperatorAlert:
        """Create and persist an operator alert."""
        alert_id = f"alt_{uuid.uuid4().hex[:12]}"
        async with db_session.get_tenant_session(tenant_id) as session:
            await self.ensure_tenant_exists(session, tenant_id)
            alert = OperatorAlert(
                alert_id=alert_id,
                tenant_id=tenant_id,
                alert_type=alert_type,
                severity=severity,
                title=title,
                description=description,
                threshold=threshold,
                current_value=current_value,
                status="active",
                created_at=datetime.now(UTC),
            )
            session.add(alert)
            await session.flush()
            return alert

    async def list_alerts(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[OperatorAlert], int, int]:
        """List operator alerts for a tenant with counts for total and active."""
        async with db_session.get_tenant_session(tenant_id) as session:
            # Active alerts count
            active_count_stmt = select(func.count(OperatorAlert.alert_id)).where(
                OperatorAlert.tenant_id == tenant_id,
                OperatorAlert.status == "active",
            )
            active_count = (await session.execute(active_count_stmt)).scalar() or 0

            # Base query
            query = select(OperatorAlert).where(OperatorAlert.tenant_id == tenant_id)
            if status:
                query = query.where(OperatorAlert.status == status.lower())

            # Total filtered count
            total_stmt = select(func.count()).select_from(query.subquery())
            total = (await session.execute(total_stmt)).scalar() or 0

            # Paged query
            paged = query.order_by(OperatorAlert.created_at.desc()).offset(offset).limit(limit)
            alerts = (await session.execute(paged)).scalars().all()
            return list(alerts), total, active_count

    async def acknowledge_alert(
        self,
        tenant_id: str,
        alert_id: str,
        operator_id: str | None = None,
    ) -> OperatorAlert | None:
        """Acknowledge an active operator alert."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(OperatorAlert).where(
                OperatorAlert.tenant_id == tenant_id,
                OperatorAlert.alert_id == alert_id,
            )
            alert = (await session.execute(stmt)).scalar_one_or_none()
            if not alert:
                return None

            alert.status = "acknowledged"
            alert.acknowledged_at = datetime.now(UTC)
            alert.acknowledged_by = operator_id or "operator"
            await session.flush()
            return alert

    async def resolve_alert(self, tenant_id: str, alert_id: str) -> OperatorAlert | None:
        """Resolve an operator alert."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(OperatorAlert).where(
                OperatorAlert.tenant_id == tenant_id,
                OperatorAlert.alert_id == alert_id,
            )
            alert = (await session.execute(stmt)).scalar_one_or_none()
            if not alert:
                return None

            alert.status = "resolved"
            alert.resolved_at = datetime.now(UTC)
            await session.flush()
            return alert

    async def create_report(
        self,
        tenant_id: str,
        title: str,
        start_date: datetime,
        end_date: datetime,
        model_id: str | None = None,
        risk_tier: str | None = None,
        idempotency_key: str | None = None,
    ) -> AuditReport:
        """Create and persist a pending audit report record."""
        report_id = f"rep_{uuid.uuid4().hex[:12]}"
        async with db_session.get_tenant_session(tenant_id) as session:
            await self.ensure_tenant_exists(session, tenant_id)
            report = AuditReport(
                report_id=report_id,
                tenant_id=tenant_id,
                title=title,
                start_date=start_date,
                end_date=end_date,
                model_id=model_id,
                risk_tier=risk_tier,
                status="PENDING",
                summary={},
                storage_key=None,
                idempotency_key=idempotency_key,
                created_at=datetime.now(UTC),
            )
            session.add(report)
            await session.flush()
            return report

    async def get_report_by_id(self, tenant_id: str, report_id: str) -> AuditReport | None:
        """Fetch audit report by ID enforcing tenant isolation."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(AuditReport).where(
                AuditReport.tenant_id == tenant_id,
                AuditReport.report_id == report_id,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def get_report_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str, window_hours: int = 1
    ) -> AuditReport | None:
        """Check for existing recent report with matching idempotency key within time window."""
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(AuditReport)
                .where(
                    AuditReport.tenant_id == tenant_id,
                    AuditReport.idempotency_key == idempotency_key,
                    AuditReport.created_at >= cutoff,
                    AuditReport.status.in_(["PENDING", "PROCESSING", "COMPLETED"]),
                )
                .order_by(AuditReport.created_at.desc())
                .limit(1)
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def update_report_status(
        self,
        tenant_id: str,
        report_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        storage_key: str | None = None,
    ) -> AuditReport | None:
        """Update audit report status, summary metrics, and storage key."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(AuditReport).where(
                AuditReport.tenant_id == tenant_id,
                AuditReport.report_id == report_id,
            )
            report = (await session.execute(stmt)).scalar_one_or_none()
            if not report:
                return None

            report.status = status
            if summary is not None:
                report.summary = summary
            if storage_key is not None:
                report.storage_key = storage_key
            if status in ("COMPLETED", "FAILED"):
                report.completed_at = datetime.now(UTC)

            await session.flush()
            return report

    async def get_sessions_for_audit(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
        model_id: str | None = None,
        risk_tier: str | None = None,
    ) -> list[VerificationSession]:
        """Fetch verification sessions within an audit date range with optional filtering."""
        async with db_session.get_tenant_session(tenant_id) as session:
            query = select(VerificationSession).where(
                VerificationSession.tenant_id == tenant_id,
                VerificationSession.created_at >= start_date,
                VerificationSession.created_at <= end_date,
            )
            if model_id:
                query = query.where(VerificationSession.model_id == model_id)
            if risk_tier:
                query = query.where(VerificationSession.risk_tier == risk_tier.upper())

            query = query.order_by(VerificationSession.created_at.asc())
            return list((await session.execute(query)).scalars().all())

    async def get_kb_document_by_filename(self, tenant_id: str, filename: str) -> KBDocumentRecord | None:
        """Fetch KB document metadata by tenant and filename."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.filename == filename,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def get_kb_document_by_id(self, tenant_id: str, document_id: str) -> KBDocumentRecord | None:
        """Fetch KB document metadata by tenant and document_id enforcing tenant isolation."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.document_id == document_id,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def list_kb_documents(self, tenant_id: str) -> list[KBDocumentRecord]:
        """List all KB documents for a tenant ordered by creation date."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(KBDocumentRecord)
                .where(KBDocumentRecord.tenant_id == tenant_id)
                .order_by(KBDocumentRecord.created_at.desc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def upsert_kb_document(
        self,
        tenant_id: str,
        document_id: str,
        filename: str,
        content_hash: str,
        chunks_count: int = 0,
        collection_name: str = "default_kb",
        status: str = "INDEXED",
        generation: int | None = None,
    ) -> KBDocumentRecord:
        """Upsert KB document metadata record for tenant using PostgreSQL atomic
        ON CONFLICT with generation tracking.
        """
        now = datetime.now(UTC)
        async with db_session.get_tenant_session(tenant_id) as session:
            await self.ensure_tenant_exists(session, tenant_id)
            set_dict: dict[str, Any] = {
                "document_id": document_id,
                "content_hash": content_hash,
                "chunks_count": chunks_count,
                "collection_name": collection_name,
                "status": status,
                "updated_at": now,
            }
            if generation is not None:
                set_dict["generation"] = generation
            else:
                set_dict["generation"] = KBDocumentRecord.generation + 1

            insert_stmt = (
                pg_insert(KBDocumentRecord)
                .values(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    filename=filename,
                    content_hash=content_hash,
                    chunks_count=chunks_count,
                    collection_name=collection_name,
                    status=status,
                    generation=generation if generation is not None else 1,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "filename"],
                    set_=set_dict,
                )
                .returning(KBDocumentRecord)
            )
            result = await session.execute(insert_stmt)
            doc = result.scalar_one()
            await session.flush()
            return doc

    async def update_kb_document_status(
        self,
        tenant_id: str,
        document_id: str,
        chunks_count: int,
        status: str = "INDEXED",
        content_hash: str | None = None,
        generation: int | None = None,
    ) -> KBDocumentRecord | None:
        """Update indexed status and chunk count of a KB document conditional on generation."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.document_id == document_id,
            )
            doc = (await session.execute(stmt)).scalar_one_or_none()
            if not doc:
                return None
            if generation is not None and doc.generation > generation:
                logger.warning(
                    "Stale generation update rejected",
                    tenant_id=tenant_id,
                    document_id=document_id,
                    task_generation=generation,
                    current_generation=doc.generation,
                )
                return None
            doc.chunks_count = chunks_count
            doc.status = status
            if content_hash is not None:
                doc.content_hash = content_hash
            if generation is not None:
                doc.generation = generation
            doc.updated_at = datetime.now(UTC)
            await session.flush()
            return doc

    async def delete_kb_document(self, tenant_id: str, document_id: str) -> bool:
        """Delete KB document metadata record scoped strictly to tenant."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.document_id == document_id,
            )
            doc = (await session.execute(stmt)).scalar_one_or_none()
            if not doc:
                return False
            await session.delete(doc)
            await session.flush()
            return True

    async def get_active_kb_generations(self, tenant_id: str) -> dict[str, int]:
        """Fetch mapping of {document_id: authoritative_generation} for all INDEXED documents of tenant."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord.document_id, KBDocumentRecord.generation).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.status == "INDEXED",
            )
            rows = (await session.execute(stmt)).all()
            return {row[0]: row[1] for row in rows}

    async def reconcile_stale_pending_kb_documents(
        self,
        tenant_id: str,
        stale_threshold_seconds: int = 300,
        qdrant_client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Reconcile stale PENDING documents for tenant.

        Detects orphaned pending uploads or uncommitted worker completions:
        1. If record is PENDING and age >= stale_threshold_seconds:
           - Check vector store for points matching (tenant_id, document_id, generation).
           - If vector points exist: promote to INDEXED (worker indexed chunks, but status commit blipped).
           - If vector points DO NOT exist:
             - Mark as FAILED (orphaned pending upload; publish unconfirmed).
        2. Invariant: Never rolls back an already INDEXED generation.
        3. Invariant: Never enqueues duplicate ingestion jobs.
        """
        now = datetime.now(UTC)
        reconciled: list[dict[str, Any]] = []

        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == tenant_id,
                KBDocumentRecord.status == "PENDING",
            )
            pending_docs = list((await session.execute(stmt)).scalars().all())

            for doc in pending_docs:
                age_seconds = (now - doc.updated_at).total_seconds()
                if age_seconds < stale_threshold_seconds:
                    continue

                points_count = 0
                if qdrant_client is not None:
                    try:
                        from qdrant_client.http import models as qmodels

                        cnt_res = qdrant_client.count(
                            collection_name=doc.collection_name,
                            count_filter=qmodels.Filter(
                                must=[
                                    qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_id)),
                                    qmodels.FieldCondition(
                                        key="document_id", match=qmodels.MatchValue(value=doc.document_id)
                                    ),
                                    qmodels.FieldCondition(
                                        key="generation", match=qmodels.MatchValue(value=doc.generation)
                                    ),
                                ]
                            ),
                            exact=True,
                        )
                        points_count = cnt_res.count
                    except Exception as exc:
                        logger.warning("Could not probe Qdrant during pending reconciliation", error=str(exc))

                # Check test-only in-memory storage fallback if qdrant has 0 points
                if points_count == 0:
                    try:
                        from gateway.routes.knowledge_base import _kb_service

                        mem_docs = _kb_service._in_memory_docs.get(tenant_id, [])
                        for md in mem_docs:
                            if md.get("document_id") == doc.document_id and md.get("generation") == doc.generation:
                                points_count = md.get("chunks_count", len(md.get("chunks", [])))
                                break
                    except Exception:
                        pass

                if points_count > 0:
                    doc.status = "INDEXED"
                    doc.chunks_count = points_count
                    doc.updated_at = now
                    reconciled.append(
                        {
                            "document_id": doc.document_id,
                            "generation": doc.generation,
                            "previous_status": "PENDING",
                            "new_status": "INDEXED",
                            "reason": "Vector points verified present in vector store",
                            "points_count": points_count,
                        }
                    )
                else:
                    doc.status = "FAILED"
                    doc.updated_at = now
                    reconciled.append(
                        {
                            "document_id": doc.document_id,
                            "generation": doc.generation,
                            "previous_status": "PENDING",
                            "new_status": "FAILED",
                            "reason": "Orphaned pending upload; publish unconfirmed and no vector points found",
                            "points_count": 0,
                        }
                    )

            await session.flush()
        return reconciled


default_persistence_service = PostgresPersistenceService()
