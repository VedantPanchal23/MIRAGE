"""Gate 5 Outcome Assurance and Reality Verification API routes for MIRAGE 3.0."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import OutcomeVerificationRecord
from gateway.middleware.auth import get_current_auth
from services.reality_verifier import reality_verifier_service
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    OutcomeReconciliationRequest,
    OutcomeReconciliationResult,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
)

router = APIRouter(prefix="/v1/outcomes", tags=["Gate 5 Outcome Assurance"])


@router.post(
    "/verify",
    response_model=OutcomeVerificationContract,
    summary="Execute Gate 5 Reality Verification for an action",
)
async def verify_action_outcome(
    request: OutcomeVerificationRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> OutcomeVerificationContract:
    """Execute reality verification probe against target system and persist outcome contract."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR, Role.API_CLIENT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{auth.role.value}' is not authorized to trigger reality verification probes.",
        )
    return await reality_verifier_service.verify_action_outcome(request, auth)


@router.get(
    "/{outcome_id}",
    response_model=OutcomeVerificationContract,
    summary="Get Gate 5 Outcome Verification record by ID",
)
async def get_outcome_by_id(
    outcome_id: str,
    auth: AuthContext = Depends(get_current_auth),
) -> OutcomeVerificationContract:
    """Fetch authoritative outcome verification record under strict tenant isolation."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = select(OutcomeVerificationRecord).where(
            OutcomeVerificationRecord.id == outcome_id,
            OutcomeVerificationRecord.tenant_id == auth.tenant_id,
        )
        record = (await session.execute(stmt)).scalar_one_or_none()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Outcome record '{outcome_id}' not found for tenant '{auth.tenant_id}'",
            )

        return await reality_verifier_service.verify_record_against_audit_trail(session, record)


@router.get(
    "/transaction/{transaction_id}",
    response_model=list[OutcomeVerificationContract],
    summary="List all Gate 5 Outcome Verification records for a transaction",
)
async def list_outcomes_for_transaction(
    transaction_id: str,
    auth: AuthContext = Depends(get_current_auth),
) -> list[OutcomeVerificationContract]:
    """Fetch all outcome verification records for an AI Transaction under tenant boundary."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(OutcomeVerificationRecord)
            .where(
                OutcomeVerificationRecord.transaction_id == transaction_id,
                OutcomeVerificationRecord.tenant_id == auth.tenant_id,
            )
            .order_by(OutcomeVerificationRecord.created_at.asc())
        )
        records = (await session.execute(stmt)).scalars().all()

        return [
            await reality_verifier_service.verify_record_against_audit_trail(session, rec)
            for rec in records
        ]


@router.post(
    "/reconcile",
    response_model=OutcomeReconciliationResult,
    summary="Reconcile generated output text against verified outcome state",
)
async def reconcile_output_and_outcome(
    request: OutcomeReconciliationRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> OutcomeReconciliationResult:
    """Validate Output <-> Outcome consistency: detect false claims of success on unverified sinks."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = select(OutcomeVerificationRecord).where(
            OutcomeVerificationRecord.id == request.outcome_id,
            OutcomeVerificationRecord.tenant_id == auth.tenant_id,
        )
        record = (await session.execute(stmt)).scalar_one_or_none()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Outcome record '{request.outcome_id}' not found for tenant '{auth.tenant_id}'",
            )

        contract = await reality_verifier_service.verify_record_against_audit_trail(session, record)

        return reality_verifier_service.reconcile_output_with_outcome(
            response_text=request.response_text,
            outcome_contract=contract,
            transaction_id=request.transaction_id,
            action_id=request.action_id,
            auth_tenant_id=auth.tenant_id,
        )
