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
from services.audit_ledger import AuditLedgerService
from services.reality_verifier import reality_verifier_service
from shared.logging import get_logger
from shared.schemas.audit import (
    AuditEvidenceBundle,
    AuditIntegrityReport,
    AuditIntegrityStatus,
    CheckpointModel,
    TrustAssuranceLevel,
    compute_checkpoint_canonical_string,
    is_valid_sha256_hex,
    verify_checkpoint_signature,
)
from shared.schemas.auth import AuthContext, Role
from shared.telemetry.metrics import (
    record_anchor_status,
    record_audit_integrity_check,
)

router = APIRouter(prefix="/v1/audit", tags=["Audit & Compliance"])
logger = get_logger("audit_routes")


class NLQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query text, e.g. 'Show critical risk sessions'")


@router.post("/verify-chain")
async def verify_audit_chain(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Verify the cryptographic SHA-256 hash chain across all audit logs for the calling tenant.

    Fails closed: Authoritative PostgreSQL verification is required.
    Does NOT fall back to in-memory/local stores on DB failure or unavailability.
    """
    try:
        return await AuditService.verify_audit_hash_chain_authoritative(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("Authoritative PostgreSQL audit chain verification failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authoritative audit chain verification unavailable: {exc}",
        ) from exc


@router.get("/diagnostics/local-chain")
async def get_diagnostic_local_chain(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Diagnostic-only check of process-local in-memory audit store.

    Explicitly labeled: Does NOT satisfy authoritative compliance or Gate 5 verification requirements.
    """
    res = AuditService.verify_audit_hash_chain(tenant_id=tenant_id)
    return {
        **res,
        "source": "local_diagnostic_store",
        "assurance_level": "DIAGNOSTIC_ONLY",
        "authoritative": False,
        "warning": "This result reflects process-local memory only and is NOT authoritative.",
    }


@router.get("/report/{session_id}")
async def get_compliance_report(
    session_id: str,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Generate a compliance verification certificate and report for an inspected session.

    Fails closed: Requires real session in PostgreSQL. Never generates dummy certificates.
    """
    from db.persistence import default_persistence_service

    session_record, claims_records = await default_persistence_service.get_session_with_claims(
        tenant_id=tenant_id, session_id=session_id
    )
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found for tenant '{tenant_id}'",
        )

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
                "claim_id": c.id,
                "text": c.claim_text,
                "status": c.status,
                "risk_score": c.risk_score,
            }
            for c in claims_records
        ],
        "signal_attribution": claims_records[0].signal_attribution if claims_records else {},
    }
    return AuditService.generate_compliance_report(session_id=session_id, session_data=session_data)


@router.get("/report/{session_id}/pdf")
async def get_compliance_report_pdf(
    session_id: str,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> Response:
    """Generate and stream a single-session compliance verification certificate as PDF.

    Fails closed: Requires real session in PostgreSQL. Never generates dummy PDF certificates.
    """
    from analytics.pdf_service import default_pdf_generator
    from db.persistence import default_persistence_service

    session_record, claims_records = await default_persistence_service.get_session_with_claims(
        tenant_id=tenant_id, session_id=session_id
    )
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found for tenant '{tenant_id}'",
        )

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
                "claim_id": c.id,
                "text": c.claim_text,
                "status": c.status,
                "risk_score": c.risk_score,
            }
            for c in claims_records
        ],
        "signal_attribution": claims_records[0].signal_attribution if claims_records else {},
    }
    report_data = AuditService.generate_compliance_report(session_id=session_id, session_data=session_data)
    pdf_bytes = default_pdf_generator.generate_session_certificate_pdf(report_data["session"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate_{session_id}.pdf"'},
    )


@router.get("/export")
async def export_tenant_audit_logs(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_EXPORT)),
) -> Response:
    """Export all audit logs and verification records for tenant in JSON Lines format (GDPR Art. 20).

    Fails closed: Authoritative PostgreSQL export is required. No local mock fallback.
    """
    try:
        lines = await AuditService.export_tenant_data_jsonl_authoritative(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("Authoritative export query failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authoritative audit export unavailable: {exc}",
        ) from exc

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
    trust_tier: str = Field(default="LOCAL_UNANCHORED")
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

    # External witness anchoring is unsupported without independent external witness evidence
    if request.trust_tier == "EXTERNALLY_ANCHORED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "External witness attestation (EXTERNALLY_ANCHORED) is currently unsupported; "
                "internal HMAC notarization provides LOCAL_UNANCHORED assurance only."
            ),
        )

    # Validate hash format
    if not is_valid_sha256_hex(request.checkpoint_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid checkpoint hash format: '{request.checkpoint_hash}'",
        )

    # Validate sequence 0 is reserved strictly for genesis sentinel
    from shared.schemas.audit import GENESIS_ROOT_HASH

    if request.sequence_number == 0 and request.checkpoint_hash.lower() != GENESIS_ROOT_HASH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sequence number 0 is reserved strictly for genesis sentinel root hash.",
        )

    derived_tier = (
        TrustAssuranceLevel.GENESIS_SENTINEL.value
        if request.sequence_number == 0
        else TrustAssuranceLevel.LOCAL_UNANCHORED.value
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
                trust_tier=derived_tier,
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
                    "trust_tier": derived_tier,
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
        trust_tier=TrustAssuranceLevel(derived_tier),
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
        "trust_tier": derived_tier,
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
        if getattr(res, "rowcount", 0) == 0:
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


class AuditExportBundleRequest(BaseModel):
    """Payload for requesting an authoritative compliance evidence bundle export."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    transaction_id: str | None = None
    session_id: str | None = None
    limit: int = Field(default=500, ge=1, le=1000)


class CreateAnchorRequest(BaseModel):
    """Payload for committing current audit ledger head to external anchor storage."""

    signer_identity: str = Field(default="notary:system_primary", description="Notary signer identity")
    ledger_identity: str = Field(default="audit_logs", description="Target ledger identity")


@router.get("/events", summary="Query tenant audit events with pagination and filters")
async def get_audit_events(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    event_type: str | None = None,
    action_id: str | None = None,
    transaction_id: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, Any]:
    """Query paginated audit log events with strict tenant isolation."""
    if not auth.has_permission(Permission.AUDIT_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: missing AUDIT_READ scope",
        )
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        return await AuditLedgerService.query_events(
            session=session,
            tenant_id=auth.tenant_id,
            start_time=start_time,
            end_time=end_time,
            event_type=event_type,
            action_id=action_id,
            transaction_id=transaction_id,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )


@router.get("/integrity", summary="Verify audit log hash chain and external anchor status")
async def get_audit_integrity(
    auth: AuthContext = Depends(get_current_auth),
) -> AuditIntegrityReport:
    """Verify cryptographic hash chain integrity and external anchor consistency for tenant."""
    if not auth.has_permission(Permission.AUDIT_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: missing AUDIT_READ scope",
        )
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        report = await AuditLedgerService.verify_with_anchor(session, auth.tenant_id)
        record_audit_integrity_check(report.status.value.lower())
        if report.status in (AuditIntegrityStatus.ANCHORED, AuditIntegrityStatus.ANCHOR_STALE):
            record_anchor_status("anchored" if report.status == AuditIntegrityStatus.ANCHORED else "stale")
        elif report.status == AuditIntegrityStatus.ANCHOR_UNAVAILABLE:
            record_anchor_status("unavailable")
        elif report.status == AuditIntegrityStatus.INTEGRITY_FAILURE:
            record_anchor_status("invalid")
        return report


@router.post("/export-bundle", summary="Export cryptographically sealed compliance evidence bundle")
async def export_audit_evidence_bundle(
    request: AuditExportBundleRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> AuditEvidenceBundle:
    """Export self-contained, digest-verified compliance bundle covering events and anchor verification."""
    if not auth.has_permission(Permission.AUDIT_EXPORT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: missing AUDIT_EXPORT scope",
        )
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        return await AuditLedgerService.export_evidence_bundle(
            session=session,
            tenant_id=auth.tenant_id,
            start_time=request.start_time,
            end_time=request.end_time,
            transaction_id=request.transaction_id,
            session_id=request.session_id,
            limit=request.limit,
        )


@router.post("/anchor", summary="Commit current audit ledger head to external anchor backend")
async def create_audit_anchor(
    request: CreateAnchorRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, Any]:
    """Create a signed checkpoint and commit an external anchor outside mutable DB rows."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Control plane violation: only administrators can commit audit anchors",
        )
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        try:
            cp, proof = await AuditLedgerService.create_checkpoint_and_anchor(
                session=session,
                tenant_id=auth.tenant_id,
                signer_identity=request.signer_identity,
                ledger_identity=request.ledger_identity,
            )
            record_anchor_status("anchored")
            return {
                "status": "ANCHORED",
                "tenant_id": auth.tenant_id,
                "checkpoint": cp.model_dump(mode="json"),
                "anchor": proof.model_dump(mode="json"),
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

