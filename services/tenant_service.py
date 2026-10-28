"""Tenant Administration and Lifecycle Service.

Authoritatively governs tenant provisioning, updates, suspension, reactivations,
and safe offboarding under PostgreSQL RLS and audit chain invariants.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    ActorIdentity,
    ApiCredential,
    Tenant,
    TenantAuditLedger,
    TenantBudgetRecord,
    User,
)
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.tenant import (
    TenantCreateRequest,
    TenantListResponse,
    TenantRegistrationRequest,
    TenantRegistrationResponse,
    TenantResponse,
    TenantStatus,
    TenantUpdateRequest,
)

logger = get_logger("tenant_service")


class TenantService:
    """Authoritative service for tenant account lifecycle management."""

    async def list_tenants(
        self,
        auth: AuthContext,
        limit: int = 50,
        cursor: str | None = None,
        session: AsyncSession | None = None,
    ) -> TenantListResponse:
        """List tenants within the caller's authorized administrative scope."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant administration requires SUPER_ADMIN or TENANT_ADMIN role",
            )

        async def _execute(s: AsyncSession) -> TenantListResponse:
            stmt = select(Tenant)
            if auth.role != Role.SUPER_ADMIN:
                # Ordinary tenant administrators are strictly scoped to their own tenant
                stmt = stmt.where(Tenant.id == auth.tenant_id)
            else:
                if cursor:
                    stmt = stmt.where(Tenant.id > cursor)
                stmt = stmt.order_by(Tenant.id.asc()).limit(limit + 1)

            res = await s.execute(stmt)
            tenants = list(res.scalars().all())

            next_cursor = None
            if auth.role == Role.SUPER_ADMIN and len(tenants) > limit:
                next_cursor = tenants[-1].id
                tenants = tenants[:limit]

            count_stmt = select(func.count(Tenant.id))
            if auth.role != Role.SUPER_ADMIN:
                count_stmt = count_stmt.where(Tenant.id == auth.tenant_id)
            total = (await s.execute(count_stmt)).scalar() or len(tenants)

            return TenantListResponse(
                tenants=[TenantResponse.model_validate(t) for t in tenants],
                total=total,
                next_cursor=next_cursor,
            )

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def get_tenant(
        self,
        auth: AuthContext,
        tenant_id: str,
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Retrieve tenant details with strict authorization checks."""
        if auth.role != Role.SUPER_ADMIN and auth.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant access prohibited: unauthorized to view another tenant",
            )

        async def _execute(s: AsyncSession) -> TenantResponse:
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_id}' not found",
                )
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def create_tenant(
        self,
        auth: AuthContext,
        req: TenantCreateRequest,
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Transactionally provision a new tenant, default identity, audit ledger, and budget."""
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant provisioning is strictly restricted to SUPER_ADMIN",
            )

        target_id = req.tenant_id or f"tenant_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantResponse:
            # Check for existing tenant
            existing = await s.get(Tenant, target_id)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{target_id}' already exists",
                )

            # Generate initial bootstrap api key hash
            bootstrap_hash = compute_sha256(f"{target_id}:bootstrap:{uuid.uuid4().hex}")

            tenant = Tenant(
                id=target_id,
                name=req.name,
                api_key_hash=bootstrap_hash,
                tier=req.tier,
                scs_enabled=req.scs_enabled,
                pii_detection_enabled=req.pii_detection_enabled,
                status=TenantStatus.ACTIVE.value,
                created_at=now,
                updated_at=now,
            )
            s.add(tenant)
            await s.flush()

            # Create default User record
            admin_user = req.admin_user_id or f"admin_{target_id}"
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user = User(
                id=user_id,
                tenant_id=target_id,
                external_subject=admin_user,
                display_name=f"{req.name} Admin",
                role=Role.TENANT_ADMIN.value,
                active=True,
                created_at=now,
            )
            s.add(user)
            await s.flush()

            # Create default TenantAdmin identity
            actor = ActorIdentity(
                id=f"id_{uuid.uuid4().hex[:12]}",
                tenant_id=target_id,
                subject=admin_user,
                user_id=user_id,
                role=Role.TENANT_ADMIN.value,
                principal_type="user",
                active=True,
                created_at=now,
            )
            s.add(actor)

            # Create tenant audit ledger
            ledger = TenantAuditLedger(
                tenant_id=target_id,
                head_chain_hash="0" * 64,
                sequence_number=0,
                created_at=now,
                updated_at=now,
            )
            s.add(ledger)

            # Create default tenant budget
            budget = TenantBudgetRecord(
                id=f"bg_{uuid.uuid4().hex[:12]}",
                tenant_id=target_id,
                currency="USD",
                total_budget_micros=100_000_000,  # $100.00 initial default
                allocated_micros=0,
                reserved_micros=0,
                spent_micros=0,
                reset_period="MONTHLY",
                hard_limit=True,
                is_active=True,
                created_at=now,
            )
            s.add(budget)

            # Create default tenant governance policy
            from db.models import Policy

            default_policy = Policy(
                id=f"pol_{target_id}_default",
                tenant_id=target_id,
                name="default_governance_policy",
                version=1,
                rules={
                    "effect": "ALLOW",
                    "max_risk": 75,
                    "deny_indicators": ["prompt_injection", "secret_credential"],
                },
                status="active",
                created_at=now,
            )
            s.add(default_policy)

            await s.flush()

            # Record audit event
            await self._record_audit(
                session=s,
                tenant_id=target_id,
                action="TENANT_PROVISIONED",
                actor_id=auth.identity_id or auth.user_id,
                details={"name": req.name, "tier": req.tier},
            )

            logger.info("Provisioned new tenant", tenant_id=target_id, name=req.name, tier=req.tier)
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(target_id) as s:
            return await _execute(s)

    async def register_tenant(
        self,
        req: TenantRegistrationRequest,
        session: AsyncSession | None = None,
    ) -> TenantRegistrationResponse:
        """Self-service enterprise onboarding: provisions tenant, user, identity, API key, and budget."""
        from gateway.middleware.auth import create_access_token
        from services.api_key_service import generate_secure_api_key

        target_id = req.tenant_id or f"tenant_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantRegistrationResponse:
            existing = await s.get(Tenant, target_id)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{target_id}' already exists",
                )

            # Generate primary API key
            raw_key, key_prefix, key_hash = generate_secure_api_key(prefix="mirage_live_")

            tenant = Tenant(
                id=target_id,
                name=req.name,
                api_key_hash=key_hash,
                tier=req.tier.lower(),
                scs_enabled=True,
                pii_detection_enabled=True,
                status=TenantStatus.ACTIVE.value,
                created_at=now,
                updated_at=now,
            )
            s.add(tenant)
            await s.flush()

            # Create User record
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user = User(
                id=user_id,
                tenant_id=target_id,
                external_subject=req.admin_email,
                display_name=f"{req.name} Administrator",
                role=Role.TENANT_ADMIN.value,
                active=True,
                created_at=now,
            )
            s.add(user)
            await s.flush()

            # Create ActorIdentity record
            actor_id = f"id_{uuid.uuid4().hex[:12]}"
            actor = ActorIdentity(
                id=actor_id,
                tenant_id=target_id,
                subject=req.admin_email,
                principal_type="user",
                role=Role.TENANT_ADMIN.value,
                user_id=user_id,
                active=True,
                created_at=now,
            )
            s.add(actor)
            await s.flush()

            # Create primary ApiCredential
            key_id = f"key_{uuid.uuid4().hex[:12]}"
            cred = ApiCredential(
                id=key_id,
                tenant_id=target_id,
                identity_id=actor_id,
                name="Primary Production API Key",
                key_prefix=key_prefix,
                key_hash=key_hash,
                scopes=["*"],
                created_at=now,
            )
            s.add(cred)

            # Create tenant audit ledger
            ledger = TenantAuditLedger(
                tenant_id=target_id,
                head_chain_hash="0" * 64,
                sequence_number=0,
                created_at=now,
                updated_at=now,
            )
            s.add(ledger)

            # Determine initial budget based on subscription tier
            tier_budgets = {
                "developer": 5_000_000,
                "free": 5_000_000,
                "business": 500_000_000,
                "growth": 500_000_000,
                "enterprise": 5_000_000_000,
            }
            total_micros = tier_budgets.get(req.tier.lower(), 500_000_000)

            budget = TenantBudgetRecord(
                id=f"bg_{uuid.uuid4().hex[:12]}",
                tenant_id=target_id,
                currency="USD",
                total_budget_micros=total_micros,
                allocated_micros=0,
                reserved_micros=0,
                spent_micros=0,
                reset_period="MONTHLY",
                hard_limit=True,
                is_active=True,
                created_at=now,
            )
            s.add(budget)

            # Create default tenant governance policy
            from db.models import Policy

            default_policy = Policy(
                id=f"pol_{target_id}_default",
                tenant_id=target_id,
                name="default_governance_policy",
                version=1,
                rules={
                    "effect": "ALLOW",
                    "max_risk": 75,
                    "deny_indicators": ["prompt_injection", "secret_credential"],
                },
                status="active",
                created_at=now,
            )
            s.add(default_policy)
            await s.flush()

            # Record audit event
            await self._record_audit(
                session=s,
                tenant_id=target_id,
                action="TENANT_REGISTERED",
                actor_id=actor_id,
                details={"name": req.name, "tier": req.tier, "admin_email": req.admin_email},
            )

            # Issue initial JWT for immediate operator access
            access_token = create_access_token(
                tenant_id=target_id,
                role=Role.TENANT_ADMIN,
                user_id=req.admin_email,
            )

            logger.info("Self-registered new enterprise tenant", tenant_id=target_id, name=req.name, tier=req.tier)
            return TenantRegistrationResponse(
                tenant_id=target_id,
                name=req.name,
                tier=req.tier.lower(),
                admin_user_id=user_id,
                admin_identity_id=actor_id,
                api_key=raw_key,
                api_key_id=key_id,
                access_token=access_token,
                token_type="bearer",
                created_at=now,
            )

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(target_id) as s:
            return await _execute(s)

    async def update_tenant(
        self,
        auth: AuthContext,
        tenant_id: str,
        req: TenantUpdateRequest,
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Update permitted tenant settings with least-privilege boundary enforcement."""
        if auth.role != Role.SUPER_ADMIN and auth.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant modification prohibited",
            )
        if auth.role != Role.SUPER_ADMIN and auth.role != Role.TENANT_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant modification requires administrative privileges",
            )
        if req.tier is not None and auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Modifying subscription tier is strictly restricted to SUPER_ADMIN",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantResponse:
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_id}' not found",
                )

            if req.name is not None:
                tenant.name = req.name
            if req.tier is not None and auth.role == Role.SUPER_ADMIN:
                tenant.tier = req.tier
            if req.scs_enabled is not None:
                tenant.scs_enabled = req.scs_enabled
            if req.pii_detection_enabled is not None:
                tenant.pii_detection_enabled = req.pii_detection_enabled
            tenant.updated_at = now

            await s.flush()
            await self._record_audit(
                session=s,
                tenant_id=tenant_id,
                action="TENANT_SETTINGS_UPDATED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "name": tenant.name,
                    "tier": tenant.tier,
                    "scs_enabled": tenant.scs_enabled,
                    "pii_detection_enabled": tenant.pii_detection_enabled,
                },
            )

            logger.info("Updated tenant settings", tenant_id=tenant_id)
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def suspend_tenant(
        self,
        auth: AuthContext,
        tenant_id: str,
        reason: str,
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Suspend a tenant (SUPER_ADMIN only). Implements fail-closed auth boundary cutoff."""
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Suspending a tenant is strictly restricted to SUPER_ADMIN",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantResponse:
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_id}' not found",
                )
            if tenant.status == TenantStatus.SUSPENDED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{tenant_id}' is already SUSPENDED",
                )
            if tenant.status == TenantStatus.OFFBOARDED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{tenant_id}' is OFFBOARDED; cannot suspend an offboarded tenant",
                )

            tenant.status = TenantStatus.SUSPENDED.value
            tenant.suspension_reason = reason
            tenant.updated_at = now

            await s.flush()
            await self._record_audit(
                session=s,
                tenant_id=tenant_id,
                action="TENANT_SUSPENDED",
                actor_id=auth.identity_id or auth.user_id,
                details={"reason": reason},
            )

            logger.warning("Tenant suspended by superadmin", tenant_id=tenant_id, reason=reason)
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def reactivate_tenant(
        self,
        auth: AuthContext,
        tenant_id: str,
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Reactivate a suspended tenant (SUPER_ADMIN only)."""
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reactivating a tenant is strictly restricted to SUPER_ADMIN",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantResponse:
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_id}' not found",
                )
            if tenant.status == TenantStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{tenant_id}' is ACTIVE; reactivation not applicable",
                )
            if tenant.status == TenantStatus.OFFBOARDED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{tenant_id}' is OFFBOARDED; cannot reactivate an offboarded tenant",
                )

            tenant.status = TenantStatus.ACTIVE.value
            tenant.suspension_reason = None
            tenant.updated_at = now

            await s.flush()
            await self._record_audit(
                session=s,
                tenant_id=tenant_id,
                action="TENANT_REACTIVATED",
                actor_id=auth.identity_id or auth.user_id,
                details={},
            )

            logger.info("Tenant reactivated by superadmin", tenant_id=tenant_id)
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def offboard_tenant(
        self,
        auth: AuthContext,
        tenant_id: str,
        reason: str = "Administrative offboarding",
        session: AsyncSession | None = None,
    ) -> TenantResponse:
        """Soft-offboard a tenant with irreversible credential revocation and immutable audit trail."""
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Offboarding a tenant is strictly restricted to SUPER_ADMIN",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> TenantResponse:
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant '{tenant_id}' not found",
                )
            if tenant.status == TenantStatus.OFFBOARDED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant '{tenant_id}' is already OFFBOARDED",
                )

            tenant.status = TenantStatus.OFFBOARDED.value
            tenant.suspension_reason = f"Offboarded: {reason}"
            tenant.updated_at = now

            # Revoke all API credentials for the offboarded tenant
            creds_stmt = select(ApiCredential).where(
                ApiCredential.tenant_id == tenant_id,
                ApiCredential.revoked_at.is_(None),
            )
            creds_res = await s.execute(creds_stmt)
            for cred in creds_res.scalars().all():
                cred.revoked_at = now

            await s.flush()
            await self._record_audit(
                session=s,
                tenant_id=tenant_id,
                action="TENANT_OFFBOARDED",
                actor_id=auth.identity_id or auth.user_id,
                details={"reason": reason},
            )

            logger.warning("Tenant offboarded", tenant_id=tenant_id, reason=reason)
            return TenantResponse.model_validate(tenant)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def _record_audit(
        self,
        session: AsyncSession,
        tenant_id: str,
        action: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        """Record an administrative audit event preserving hash chain integrity."""
        from services.audit_ledger import AuditLedgerService

        await AuditLedgerService.append_entry(
            session=session,
            tenant_id=tenant_id,
            event_type=f"ADMIN_{action}",
            actor_identity_id=actor_id,
            reason=f"Administrative operation: {action}",
            event_payload=details,
        )


tenant_service = TenantService()
