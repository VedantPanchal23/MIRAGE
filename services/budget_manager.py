"""Authoritative, concurrency-safe Budget Manager service for MIRAGE 3.0."""

import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    BudgetReservationRecord,
    ModelPricingProfileRecord,
    TenantBudgetRecord,
    TransactionCostRecord,
)
from shared.logging import get_logger
from shared.schemas.budget import (
    BudgetReservation,
    BudgetReservationRequest,
    BudgetResetPeriod,
    BudgetSettlementRequest,
    ReservationStatus,
    TenantBudget,
    TransactionCostRecordSchema,
)

logger = get_logger("budget_manager")

DEFAULT_TENANT_BUDGET_MICROS = 100_000_000  # $100.00 default allowance


class BudgetManagerService:
    """Manages tenant budgets, multi-dimensional bounds, atomic reservations, and settlements."""

    async def get_or_create_tenant_budget_record(
        self,
        session: AsyncSession,
        tenant_id: str,
        default_limit_micros: int = DEFAULT_TENANT_BUDGET_MICROS,
    ) -> TenantBudgetRecord:
        """Fetch existing tenant budget record or create default ledger record with lock."""
        stmt = select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == tenant_id).with_for_update()
        record = (await session.execute(stmt)).scalar_one_or_none()
        if record is None:
            # Ensure parent tenant exists in tenants table
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, api_key_hash, tier, created_at) "
                    "VALUES (:tid, :tid, :h, 'free', NOW()) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"tid": tenant_id, "h": f"key_{tenant_id}"[:32]},
            )
            now = datetime.now(UTC)
            record = TenantBudgetRecord(
                id=f"tb_{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                currency="USD",
                total_budget_micros=default_limit_micros,
                allocated_micros=0,
                reserved_micros=0,
                spent_micros=0,
                reset_period="MONTHLY",
                reset_at=now + timedelta(days=30),
                hard_limit=True,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            await session.flush()
        return record

    async def get_tenant_budget(self, tenant_id: str) -> TenantBudget:
        """Retrieve current tenant budget summary and available headroom."""
        async with db_session.get_tenant_session(tenant_id) as session:
            record = await self.get_or_create_tenant_budget_record(session, tenant_id)
            available = max(0, record.total_budget_micros - (record.spent_micros + record.reserved_micros))
            return TenantBudget(
                id=record.id,
                tenant_id=record.tenant_id,
                currency=record.currency,
                total_budget_micros=record.total_budget_micros,
                allocated_micros=record.allocated_micros,
                reserved_micros=record.reserved_micros,
                spent_micros=record.spent_micros,
                available_micros=available,
                reset_period=BudgetResetPeriod(record.reset_period),
                reset_at=record.reset_at,
                hard_limit=record.hard_limit,
                is_active=record.is_active,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    async def update_tenant_budget(
        self,
        tenant_id: str,
        total_budget_micros: int,
        hard_limit: bool = True,
        reset_period: BudgetResetPeriod = BudgetResetPeriod.MONTHLY,
    ) -> TenantBudget:
        """Update tenant budget parameters."""
        if total_budget_micros < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Budget total cannot be negative",
            )

        async with db_session.get_tenant_session(tenant_id) as session:
            record = await self.get_or_create_tenant_budget_record(session, tenant_id)
            record.total_budget_micros = total_budget_micros
            record.hard_limit = hard_limit
            record.reset_period = reset_period.value
            record.updated_at = datetime.now(UTC)
            await session.commit()

            available = max(0, record.total_budget_micros - (record.spent_micros + record.reserved_micros))
            return TenantBudget(
                id=record.id,
                tenant_id=record.tenant_id,
                currency=record.currency,
                total_budget_micros=record.total_budget_micros,
                allocated_micros=record.allocated_micros,
                reserved_micros=record.reserved_micros,
                spent_micros=record.spent_micros,
                available_micros=available,
                reset_period=BudgetResetPeriod(record.reset_period),
                reset_at=record.reset_at,
                hard_limit=record.hard_limit,
                is_active=record.is_active,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    async def reserve_budget(self, request: BudgetReservationRequest) -> BudgetReservation:
        """Atomically reserve funds under row-level lock to prevent concurrent overspend."""
        if request.estimated_cost_micros <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reservation amount must be strictly greater than 0 micros",
            )

        async with db_session.get_tenant_session(request.tenant_id) as session:
            # Check idempotency first
            exist_stmt = (
                select(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.tenant_id == request.tenant_id,
                    BudgetReservationRecord.reservation_key == request.reservation_key,
                )
                .with_for_update()
            )
            existing = (await session.execute(exist_stmt)).scalar_one_or_none()
            if existing is not None:
                return BudgetReservation(
                    id=existing.id,
                    tenant_id=existing.tenant_id,
                    transaction_id=existing.transaction_id,
                    reservation_key=existing.reservation_key,
                    amount_micros=existing.amount_micros,
                    status=ReservationStatus(existing.status),
                    expires_at=existing.expires_at,
                    created_at=existing.created_at,
                    settled_at=existing.settled_at,
                )

            # Lock tenant budget row
            budget_rec = await self.get_or_create_tenant_budget_record(session, request.tenant_id)
            if not budget_rec.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Budget for tenant '{request.tenant_id}' is deactivated",
                )

            current_usage = budget_rec.spent_micros + budget_rec.reserved_micros
            available = budget_rec.total_budget_micros - current_usage

            if budget_rec.hard_limit and (available < request.estimated_cost_micros):
                logger.warning(
                    "Tenant budget limit exceeded",
                    tenant_id=request.tenant_id,
                    total_limit=budget_rec.total_budget_micros,
                    current_usage=current_usage,
                    requested=request.estimated_cost_micros,
                )
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Budget limit exceeded for tenant '{request.tenant_id}'. "
                        f"Available: {max(0, available)} micros, requested: {request.estimated_cost_micros} micros."
                    ),
                )

            now = datetime.now(UTC)
            expires_at = now + timedelta(seconds=request.timeout_seconds)

            reservation = BudgetReservationRecord(
                id=f"res_{uuid.uuid4().hex[:16]}",
                tenant_id=request.tenant_id,
                transaction_id=request.transaction_id,
                reservation_key=request.reservation_key,
                amount_micros=request.estimated_cost_micros,
                status=ReservationStatus.RESERVED.value,
                expires_at=expires_at,
                created_at=now,
                settled_at=None,
            )
            session.add(reservation)

            budget_rec.reserved_micros += request.estimated_cost_micros
            budget_rec.updated_at = now
            await session.commit()

            return BudgetReservation(
                id=reservation.id,
                tenant_id=reservation.tenant_id,
                transaction_id=reservation.transaction_id,
                reservation_key=reservation.reservation_key,
                amount_micros=reservation.amount_micros,
                status=ReservationStatus.RESERVED,
                expires_at=expires_at,
                created_at=now,
                settled_at=None,
            )

    async def settle_budget(self, tenant_id: str, request: BudgetSettlementRequest) -> TransactionCostRecordSchema:
        """Atomically finalize actual expenditure and release unused reserved headroom."""
        async with db_session.get_tenant_session(tenant_id) as session:
            # 1. Fetch reservation
            res_stmt = (
                select(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.id == request.reservation_id,
                    BudgetReservationRecord.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            res_rec = (await session.execute(res_stmt)).scalar_one_or_none()
            if res_rec is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Budget reservation '{request.reservation_id}' not found",
                )
            if res_rec.status != ReservationStatus.RESERVED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Reservation '{request.reservation_id}' is already {res_rec.status}",
                )

            # 2. Lock tenant budget
            budget_rec = await self.get_or_create_tenant_budget_record(session, tenant_id)

            # 3. Deduct reserved and add actual spent
            reserved_amount = res_rec.amount_micros
            budget_rec.reserved_micros = max(0, budget_rec.reserved_micros - reserved_amount)
            budget_rec.spent_micros += request.actual_cost_micros
            budget_rec.updated_at = datetime.now(UTC)

            # 4. Mark reservation SETTLED
            now = datetime.now(UTC)
            res_rec.status = ReservationStatus.SETTLED.value
            res_rec.settled_at = now

            # 5. Insert itemized TransactionCostRecord
            cost_rec = TransactionCostRecord(
                id=f"cost_{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                transaction_id=res_rec.transaction_id,
                model_id=request.model_id,
                provider=request.provider,
                prompt_tokens=request.prompt_tokens,
                completion_tokens=request.completion_tokens,
                cached_tokens=request.cached_tokens,
                cost_micros=request.actual_cost_micros,
                stage=request.stage,
                created_at=now,
            )
            session.add(cost_rec)
            await session.commit()

            return TransactionCostRecordSchema(
                id=cost_rec.id,
                tenant_id=cost_rec.tenant_id,
                transaction_id=cost_rec.transaction_id,
                model_id=cost_rec.model_id,
                provider=cost_rec.provider,
                prompt_tokens=cost_rec.prompt_tokens,
                completion_tokens=cost_rec.completion_tokens,
                cached_tokens=cost_rec.cached_tokens,
                cost_micros=cost_rec.cost_micros,
                stage=cost_rec.stage,
                created_at=cost_rec.created_at,
            )

    async def release_reservation(self, tenant_id: str, reservation_id: str) -> None:
        """Release unused reservation without charging spend."""
        async with db_session.get_tenant_session(tenant_id) as session:
            res_stmt = (
                select(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.id == reservation_id,
                    BudgetReservationRecord.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            res_rec = (await session.execute(res_stmt)).scalar_one_or_none()
            if res_rec is None or res_rec.status != ReservationStatus.RESERVED.value:
                return

            budget_rec = await self.get_or_create_tenant_budget_record(session, tenant_id)
            budget_rec.reserved_micros = max(0, budget_rec.reserved_micros - res_rec.amount_micros)
            budget_rec.updated_at = datetime.now(UTC)

            res_rec.status = ReservationStatus.RELEASED.value
            res_rec.settled_at = datetime.now(UTC)
            await session.commit()

    async def reconcile_orphaned_reservations(self, max_batch_size: int = 100) -> int:
        """Periodic background reconciliation of timed-out reservations."""
        now = datetime.now(UTC)
        reconciled_count = 0

        async with db_session.get_system_session() as session:
            stmt = (
                select(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.status == ReservationStatus.RESERVED.value,
                    BudgetReservationRecord.expires_at < now,
                )
                .limit(max_batch_size)
                .with_for_update()
            )
            expired_recs = (await session.execute(stmt)).scalars().all()

            for res_rec in expired_recs:
                budget_rec = await self.get_or_create_tenant_budget_record(session, res_rec.tenant_id)
                budget_rec.reserved_micros = max(0, budget_rec.reserved_micros - res_rec.amount_micros)
                budget_rec.updated_at = now

                res_rec.status = ReservationStatus.EXPIRED.value
                res_rec.settled_at = now
                reconciled_count += 1

            if reconciled_count > 0:
                await session.commit()
                logger.info("Reconciled orphaned budget reservations", count=reconciled_count)

        return reconciled_count

    async def calculate_cost_for_model(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> int:
        """Lookup active pricing profile and calculate cost in micros."""
        async with db_session.get_system_session() as session:
            stmt = (
                select(ModelPricingProfileRecord)
                .where(
                    ModelPricingProfileRecord.model_id == model_id,
                    ModelPricingProfileRecord.is_active.is_(True),
                )
                .order_by(ModelPricingProfileRecord.created_at.desc())
                .limit(1)
            )
            profile = (await session.execute(stmt)).scalar_one_or_none()
            if profile is None:
                # Default fallback pricing if not registered: $2.50 / $10.00
                input_cost = 2500000
                output_cost = 10000000
                cached_cost = 1250000
            else:
                input_cost = profile.input_cost_per_million_micros
                output_cost = profile.output_cost_per_million_micros
                cached_cost = profile.cached_input_cost_per_million_micros

            uncached = max(0, prompt_tokens - cached_tokens)
            micros = (
                (uncached * input_cost) + (cached_tokens * cached_cost) + (completion_tokens * output_cost)
            ) / 1_000_000.0
            return int(math.ceil(micros))


budget_manager_service = BudgetManagerService()
