"""Audit helper for Gate 3 Action Governance cryptographic chaining."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from db.models import AuditLogRecord
from shared.schemas.audit import compute_sha256


async def _record_action_audit_event(
    session: Any,
    tenant_id: str,
    event_type: str,
    actor_identity_id: str | None = None,
    transaction_id: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    latest = await session.execute(
        select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
        .where(AuditLogRecord.tenant_id == tenant_id)
        .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        .limit(1)
    )
    latest_row = latest.first()
    prev_hash = latest_row[0] if latest_row and latest_row[0] is not None else ("0" * 64)
    prev_seq = latest_row[1] if latest_row and len(latest_row) > 1 and latest_row[1] is not None else 0
    seq = prev_seq + 1
    now = datetime.now(UTC)
    entry_id = f"aud_{uuid.uuid4().hex}"
    chain_payload = f"{prev_hash}:{entry_id}:{event_type}:{decision or ''}:{now.isoformat()}"
    chain_hash = compute_sha256(chain_payload)

    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=transaction_id or "action-governance",
            trace_id="action-governor",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="ACTION_ASSURANCE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=event_type,
            actor_identity_id=actor_identity_id or "system_actor",
            transaction_id=transaction_id,
            decision=decision,
            reason=reason,
            event_payload=payload or {},
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
    )
