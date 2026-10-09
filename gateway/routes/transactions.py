"""Phase 1 governed transaction and assurance API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from db import session as db_session
from db.models import AITransaction
from gateway.middleware.auth import get_current_auth
from services.control_plane import (
    _transaction_response,
    assure_input,
    cancel_transaction,
    create_transaction,
    transition_transaction,
    validate_capability,
)
from shared.schemas.auth import AuthContext
from shared.schemas.control_plane import (
    CapabilityValidationRequest,
    InputAssuranceRequest,
    InputAssuranceResult,
    PolicyDecision,
    TransactionCancelRequest,
    TransactionCreateRequest,
    TransactionResponse,
    TransactionTransitionRequest,
)

router = APIRouter(prefix="/v1", tags=["Governed Transactions"])


@router.post("/input-assurance", response_model=InputAssuranceResult)
async def input_assurance(
    request: InputAssuranceRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> InputAssuranceResult:
    """Evaluate Gate 1 without starting execution."""
    return await assure_input(auth, request)


@router.post("/transactions", response_model=TransactionResponse, status_code=201)
async def create_governed_transaction(
    request: TransactionCreateRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> TransactionResponse:
    """Create an idempotent, tenant-bound transaction after Input Assurance."""
    return await create_transaction(auth, request)


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_governed_transaction(
    transaction_id: str, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> TransactionResponse:
    """Return an existing transaction through the state-machine service."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(AITransaction, transaction_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        return _transaction_response(record)


@router.post("/transactions/{transaction_id}/transitions", response_model=TransactionResponse)
async def transition_governed_transaction(
    transaction_id: str, request: TransactionTransitionRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> TransactionResponse:
    """Apply a valid versioned state transition."""
    return await transition_transaction(auth, transaction_id, request)


@router.post("/transactions/{transaction_id}/cancel", response_model=TransactionResponse)
async def cancel_governed_transaction(
    transaction_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    request: TransactionCancelRequest | None = None,
) -> TransactionResponse:
    """Explicitly abort an active governed transaction."""
    reason = request.reason if request is not None else "Cancelled by client"
    return await cancel_transaction(auth, transaction_id, reason=reason)


@router.post("/capabilities/validate", response_model=PolicyDecision)
async def validate_governed_capability(
    request: CapabilityValidationRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> PolicyDecision:
    """Validate a scoped Phase 1 capability for the authenticated identity."""
    return await validate_capability(auth, request)
