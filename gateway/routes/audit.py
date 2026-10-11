"""Audit, Compliance Verification, and Operator Query Routes.

Implements PRD FR-AUD-01..04 & Security & Access Document §10:
- POST /v1/audit/verify-chain: Cryptographic SHA-256 hash chain verification
- GET /v1/audit/report/{session_id}: Exportable compliance audit report
- GET /v1/audit/export: GDPR Right to Portability (JSONL export)
- POST /v1/audit/query: Natural language operator query
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.audit_service import AuditService
from db import session as db_session
from db.models import AuditCheckpointRecord, AuditLogRecord
from gateway.middleware.auth import get_current_auth
from gateway.middleware.rbac import Permission, require_permission
from services.reality_verifier import reality_verifier_service
from shared.logging import get_logger
from shared.schemas.audit import (
    CheckpointModel,
    TrustAssuranceLevel,
    compute_checkpoint_canonical_string,
    is_valid_sha256_hex,
    verify_checkpoint_signature,
)
from shared.schemas.auth import AuthContext, Role

router = APIRouter(prefix="/v1/audit", tags=["Audit & Compliance"])
logger = get_logger("audit_routes")


class NLQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query text, e.g. 'Show critical risk sessions'")


@router.post("/verify-chain")
async def verify_audit_chain(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Verify the cryptographic SHA-256 hash chain across all audit logs for the calling tenant."""
    try:
        res = await AuditService.verify_audit_hash_chain_authoritative(tenant_id=tenant_id)
        if res.get("chain_status") != "EMPTY" or not res.get("valid"):
            return res
    except Exception as exc:
        logger.warning("PostgreSQL audit chain check unavailable, falling back to local store", error=str(exc))

    return AuditService.verify_audit_hash_chain(tenant_id=tenant_id)


@router.get("/report/{session_id}")
async def get_compliance_report(
    session_id: str,
    _tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Generate a compliance verification certificate and report for an inspected session."""
    report = AuditService.generate_compliance_report(session_id=session_id)
    return report


@router.get("/report/{session_id}/pdf")
async def get_compliance_report_pdf(
    session_id: str,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> Response:
    """Generate and stream a single-session compliance verification certificate as PDF."""
    from analytics.pdf_service import default_pdf_generator
    from db.models import ClaimRecord, VerificationSession
    from db.persistence import default_persistence_service

    session_record: VerificationSession | None = None
    claims_records: list[ClaimRecord] = []
    try:
        session_record, claims_records = await default_persistence_service.get_session_with_claims(
            tenant_id=tenant_id, session_id=session_id
        )
    except Exception as exc:
        logger.warning("Postgres lookup for session certificate fallback", error=str(exc))

    if session_record:
        session_data = {
            "session_id": session_record.session_id,
            "tenant_id": session_record.tenant_id,
            "model_id": session_record.model_id,
            "timestamp": session_record.created_at.isoformat() if session_record.created_at else "",
            "hrs_score": session_record.hrs_score,
            "risk_tier": session_record.risk_tier,
            "correction_applied": session_record.correction_applied,
            "claims": [
                {
                    "text": c.claim_text,
                    "status": c.status,
                    "risk_score": c.risk_score,
                }
                for c in claims_records
            ],
            "signal_attribution": claims_records[0].signal_attribution if claims_records else {},
        }
    else:
        session_data = AuditService.generate_compliance_report(session_id=session_id)

    pdf_bytes = default_pdf_generator.generate_session_certificate_pdf(session_data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate_{session_id}.pdf"'},
    )


@router.get("/export")
async def export_tenant_audit_logs(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_EXPORT)),
) -> Response:
    """Export all audit logs and verification records for tenant in JSON Lines format (GDPR Art. 20)."""
    lines: list[str] = []
    try:
        lines = await AuditService.export_tenant_data_jsonl_authoritative(tenant_id=tenant_id)
    except Exception as exc:
        logger.warning("PostgreSQL export query failed, checking local store", error=str(exc))

    if not lines:
        lines = AuditService.export_tenant_data_jsonl(tenant_id=tenant_id)

    jsonl_content = "\n".join(lines)
    return Response(
        content=jsonl_content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f"attachment; filename=mirage_audit_{tenant_id}.jsonl",
        },
    )


@router.post("/query")
async def query_audit_logs(
    request: NLQueryRequest,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Natural language query endpoint for searching audit records (PRD FR-AUD-03)."""
    matches = AuditService.natural_language_query(query=request.query, tenant_id=tenant_id)
    return {
        "query": request.query,
        "tenant_id": tenant_id,
        "total_matches": len(matches),
        "results": matches,
    }


class RegisterCheckpointRequest(BaseModel):
    checkpoint_id: str | None = None
    checkpoint_hash: str = Field(..., description="64-character hex SHA-256 chain hash")
    sequence_number: int = Field(ge=0, description="Exact monotonic sequence number in tenant ledger")
    ledger_identity: str = Field(default="audit_logs")
    signer_identity: str = Field(..., description="Identifier of authorized notary signer")
    signature: str = Field(..., description="Cryptographic HMAC-SHA256 signature")
    trust_tier: str = Field(default="EXTERNALLY_ANCHORED")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


class RevokeCheckpointRequest(BaseModel):
    checkpoint_hash: str = Field(..., description="64-character hex SHA-256 chain hash to revoke")
    reason: str = Field(default="Compromised or retired", description="Documented reason for revocation")


@router.post("/checkpoints", summary="Register an authoritative audit checkpoint (SUPER_ADMIN only)")
async def register_audit_checkpoint(
    request: RegisterCheckpointRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, Any]:
    """Register and persist a cryptographically signed audit checkpoint under control-plane authorization."""
    if auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Control plane violation: Role '{auth.role.value}' is unauthorized "
                "to register audit checkpoints. Requires SUPER_ADMIN."
            ),
        )

    # Validate hash format
    if not is_valid_sha256_hex(request.checkpoint_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid checkpoint hash format: '{request.checkpoint_hash}'",
        )

    # Validate notary signature
    key_bytes = reality_verifier_service.checkpoint_registry.notary_keys.get_key(request.signer_identity)
    if not key_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or unauthorized notary signer_identity '{request.signer_identity}'",
        )

    canon = compute_checkpoint_canonical_string(
        tenant_id=auth.tenant_id,
        ledger_identity=request.ledger_identity,
        sequence_number=request.sequence_number,
        checkpoint_hash=request.checkpoint_hash,
        issued_at_iso=request.issued_at.isoformat(),
        signer_identity=request.signer_identity,
    )
    if not verify_checkpoint_signature(key_bytes, canon, request.signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cryptographic signature verification failed for checkpoint",
        )

    # Validate expiration
    now = datetime.now(UTC)
    if request.expires_at and request.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot register expired checkpoint (expired at {request.expires_at})",
        )

    checkpoint_id = request.checkpoint_id or f"chk_{uuid.uuid4().hex[:12]}"

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        # If sequence > 0, verify sequence binding against audit_logs
        if request.sequence_number > 0:
            audit_stmt = select(AuditLogRecord).where(
                AuditLogRecord.tenant_id == auth.tenant_id,
                AuditLogRecord.sequence_number == request.sequence_number,
            )
            audit_row = (await session.execute(audit_stmt)).scalar_one_or_none()
            if not audit_row or audit_row.chain_hash != request.checkpoint_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Checkpoint sequence mismatch: audit log at sequence {request.sequence_number} "
                        f"has chain_hash '{audit_row.chain_hash if audit_row else None}', "
                        f"does not match checkpoint_hash '{request.checkpoint_hash}'"
                    ),
                )

        # Upsert AuditCheckpointRecord
        stmt = (
            pg_insert(AuditCheckpointRecord)
            .values(
                id=checkpoint_id,
                tenant_id=auth.tenant_id,
                checkpoint_hash=request.checkpoint_hash.lower().strip(),
                sequence_number=request.sequence_number,
                ledger_identity=request.ledger_identity,
                signer_identity=request.signer_identity,
                signature=request.signature,
                trust_tier=request.trust_tier,
                revoked=False,
                issued_at=request.issued_at,
                expires_at=request.expires_at,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "checkpoint_hash"],
                set_={
                    "sequence_number": request.sequence_number,
                    "ledger_identity": request.ledger_identity,
                    "signer_identity": request.signer_identity,
                    "signature": request.signature,
                    "trust_tier": request.trust_tier,
                    "revoked": False,
                    "issued_at": request.issued_at,
                    "expires_at": request.expires_at,
                },
            )
        )
        await session.execute(stmt)

    # Also register in in-memory registry
    cp_model = CheckpointModel(
        checkpoint_id=checkpoint_id,
        tenant_id=auth.tenant_id,
        checkpoint_hash=request.checkpoint_hash.lower().strip(),
        sequence_number=request.sequence_number,
        ledger_identity=request.ledger_identity,
        signer_identity=request.signer_identity,
        signature=request.signature,
        trust_tier=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
        issued_at=request.issued_at,
        expires_at=request.expires_at,
    )
    reality_verifier_service.checkpoint_registry.register_authenticated_checkpoint(cp_model)

    return {
        "status": "REGISTERED",
        "checkpoint_id": checkpoint_id,
        "tenant_id": auth.tenant_id,
        "checkpoint_hash": request.checkpoint_hash,
        "sequence_number": request.sequence_number,
        "signer_identity": request.signer_identity,
        "trust_tier": request.trust_tier,
    }


@router.post("/checkpoints/revoke", summary="Revoke an audit checkpoint (SUPER_ADMIN only)")
async def revoke_audit_checkpoint(
    request: RevokeCheckpointRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, Any]:
    """Revoke a previously registered audit checkpoint under control-plane authorization."""
    if auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Control plane violation: Role '{auth.role.value}' is unauthorized "
                "to revoke audit checkpoints. Requires SUPER_ADMIN."
            ),
        )

    h = request.checkpoint_hash.lower().strip()
    now = datetime.now(UTC)

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            update(AuditCheckpointRecord)
            .where(
                AuditCheckpointRecord.tenant_id == auth.tenant_id,
                AuditCheckpointRecord.checkpoint_hash == h,
            )
            .values(
                revoked=True,
                revoked_at=now,
                revoked_by=auth.identity_id or "super_admin",
                revocation_reason=request.reason,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Checkpoint '{h}' not found for tenant '{auth.tenant_id}'",
            )

    reality_verifier_service.checkpoint_registry.revoke_checkpoint(
        tenant_id=auth.tenant_id,
        checkpoint_hash=h,
        revoked_by=auth.identity_id or "super_admin",
        reason=request.reason,
    )

    return {
        "status": "REVOKED",
        "tenant_id": auth.tenant_id,
        "checkpoint_hash": h,
        "revoked_at": now.isoformat(),
        "reason": request.reason,
    }


@router.get("/checkpoints", summary="List audit checkpoints for tenant")
async def list_audit_checkpoints(
    auth: AuthContext = Depends(get_current_auth),
) -> list[dict[str, Any]]:
    """List all registered checkpoints for the tenant."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(AuditCheckpointRecord)
            .where(AuditCheckpointRecord.tenant_id == auth.tenant_id)
            .order_by(AuditCheckpointRecord.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "checkpoint_id": r.id,
                "tenant_id": r.tenant_id,
                "checkpoint_hash": r.checkpoint_hash,
                "sequence_number": r.sequence_number,
                "ledger_identity": r.ledger_identity,
                "signer_identity": r.signer_identity,
                "trust_tier": r.trust_tier,
                "revoked": r.revoked,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "revocation_reason": r.revocation_reason,
                "issued_at": r.issued_at.isoformat() if r.issued_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in rows
        ]
