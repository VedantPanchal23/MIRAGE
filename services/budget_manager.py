"""Authoritative, concurrency-safe Budget Manager service for MIRAGE 3.0.

Enforces:
- PostgreSQL advisory transaction locks for serialized first-time budget initialization
- Pessimistic SELECT ... FOR UPDATE row-level locking
- Strict reservation idempotency with conflicting replay rejection (HTTP 409)
- Exact integer micro-unit financial ledger accounting with zero binary float drift
- Non-masking invariant enforcement (raises integrity errors rather than max(0, ...) drift masking)
- Atomic overage verification in hard-limit mode
- Explicit multi-state lifecycle: RESERVED -> SETTLED | RELEASED | EXPIRED | RECONCILIATION_REQUIRED
"""

import hashlib
import struct
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    AccountingIncidentRecord,
    BudgetReservationRecord,
    ProviderInvocationRecord,
    TenantBudgetRecord,
    TransactionCostRecord,
)
from services.pricing_service import pricing_service
from shared.config import get_settings
from shared.config.settings import EnvironmentType
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


def _is_postgresql_session(session: AsyncSession) -> bool:
    """Detect whether session is executing against a live PostgreSQL database."""
    sync_session = getattr(session, "sync_session", None)
    sync_bind = getattr(sync_session, "bind", None) if sync_session is not None else None
    if sync_bind is not None and hasattr(sync_bind, "dialect"):
        return getattr(sync_bind.dialect, "name", None) == "postgresql"
    bind = getattr(session, "bind", None)
    if bind is not None and hasattr(bind, "dialect"):
        return getattr(bind.dialect, "name", None) == "postgresql"
    return False


async def _acquire_advisory_lock(session: AsyncSession, lock_namespace: str) -> None:
    """Acquire a PostgreSQL transaction-scoped advisory lock or fail closed in production."""
    settings = get_settings()
    is_live_postgres = _is_postgresql_session(session)

    if settings.environment == EnvironmentType.PRODUCTION and not is_live_postgres:
        raise RuntimeError(
            f"Production invariant violation: advisory lock for '{lock_namespace}' requires PostgreSQL dialect"
        )

    if is_live_postgres:
        # Compute 64-bit signed integer for pg_advisory_xact_lock
        lock_id = struct.unpack(">q", hashlib.sha256(lock_namespace.encode("utf-8")).digest()[:8])[0]
        # Must execute without blanket exception swallowing: any database error aborts operation
        await session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
    else:
        logger.warning(
            "Non-PostgreSQL dialect in %s environment: skipping advisory lock for '%s'",
            settings.environment,
            lock_namespace,
        )


class BudgetManagerService:
    """Manages tenant budgets, multi-dimensional bounds, atomic reservations, and settlements."""

    async def record_accounting_incident(
        self,
        tenant_id: str,
        incident_type: str,
        reservation_id: str | None = None,
        transaction_id: str | None = None,
        expected_micros: int | None = None,
        actual_micros: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> AccountingIncidentRecord:
        """Durable persistence for accounting anomalies, drift, and post-execution failures."""
        async with db_session.get_tenant_session(tenant_id) as session:
            inc = AccountingIncidentRecord(
                id=f"inc_{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                transaction_id=transaction_id,
                incident_type=incident_type,
                expected_micros=expected_micros,
                actual_micros=actual_micros,
                details=details or {},
                resolved=False,
                created_at=datetime.now(UTC),
            )
            session.add(inc)
            await session.commit()
            logger.critical(
                "Recorded durable accounting incident",
                tenant_id=tenant_id,
                incident_id=inc.id,
                incident_type=incident_type,
                expected_micros=expected_micros,
                actual_micros=actual_micros,
            )
            return inc

    async def record_provider_invocation(
        self,
        tenant_id: str,
        transaction_id: str,
        reservation_id: str | None,
        attempt_number: int,
        provider: str,
        model_id: str,
        status: str,
        latency_ms: float | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        cost_micros: int | None = None,
        error_message: str | None = None,
    ) -> ProviderInvocationRecord:
        """Durable persistence of each downstream provider dispatch attempt."""
        async with db_session.get_tenant_session(tenant_id) as session:
            inv = ProviderInvocationRecord(
                id=f"inv_{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                transaction_id=transaction_id,
                reservation_id=reservation_id,
                attempt_number=attempt_number,
                provider=provider,
                model_id=model_id,
                status=status,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                cost_micros=cost_micros,
                error_message=error_message,
                created_at=datetime.now(UTC),
            )
            session.add(inv)
            await session.commit()
            return inv

    async def get_or_create_tenant_budget_record(
        self,
        session: AsyncSession,
        tenant_id: str,
        default_limit_micros: int = DEFAULT_TENANT_BUDGET_MICROS,
    ) -> TenantBudgetRecord:
        """Fetch existing tenant budget record or create default ledger record under advisory lock."""
        # Acquire PostgreSQL advisory transaction lock to serialize first-time initialization
        await _acquire_advisory_lock(session, f"tenant_budget_init:{tenant_id}")

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
            available = record.total_budget_micros - (record.spent_micros + record.reserved_micros)
            return TenantBudget(
                id=record.id,
                tenant_id=record.tenant_id,
                currency=record.currency,
                total_budget_micros=record.total_budget_micros,
                allocated_micros=record.allocated_micros,
                reserved_micros=record.reserved_micros,
                spent_micros=record.spent_micros,
                available_micros=max(0, available),
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

            available = record.total_budget_micros - (record.spent_micros + record.reserved_micros)
            return TenantBudget(
                id=record.id,
                tenant_id=record.tenant_id,
                currency=record.currency,
                total_budget_micros=record.total_budget_micros,
                allocated_micros=record.allocated_micros,
                reserved_micros=record.reserved_micros,
                spent_micros=record.spent_micros,
                available_micros=max(0, available),
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
            # 0. Acquire advisory lock on reservation key to serialize concurrent requests with the same key
            await _acquire_advisory_lock(
                session, f"budget_reservation:{request.tenant_id}:{request.reservation_key}"
            )

            # 1. Enforce strict reservation idempotency
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
                # Check for conflicting reuse
                if (
                    existing.transaction_id != request.transaction_id
                    or existing.amount_micros != request.estimated_cost_micros
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Idempotency key '{request.reservation_key}' was previously reserved with conflicting "
                            f"parameters (tx={existing.transaction_id}, amount={existing.amount_micros})"
                        ),
                    )
                return BudgetReservation(
                    id=existing.id,
                    tenant_id=existing.tenant_id,
                    transaction_id=existing.transaction_id,
                    reservation_key=existing.reservation_key,
                    amount_micros=existing.amount_micros,
                    status=ReservationStatus(existing.status),
                    attempt_number=existing.attempt_number,
                    selected_provider=existing.selected_provider,
                    selected_model=existing.selected_model,
                    expires_at=existing.expires_at,
                    created_at=existing.created_at,
                    settled_at=existing.settled_at,
                )

            # 2. Lock tenant budget row
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
                attempt_number=request.attempt_number,
                selected_provider=request.selected_provider,
                selected_model=request.selected_model,
                expires_at=expires_at,
                created_at=now,
                settled_at=None,
            )
            session.add(reservation)

            budget_rec.reserved_micros += request.estimated_cost_micros
            budget_rec.updated_at = now
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Concurrently inserted reservation with same reservation_key won the race
                recheck_stmt = select(BudgetReservationRecord).where(
                    BudgetReservationRecord.tenant_id == request.tenant_id,
                    BudgetReservationRecord.reservation_key == request.reservation_key,
                )
                recheck = (await session.execute(recheck_stmt)).scalar_one_or_none()
                if recheck is not None:
                    if (
                        recheck.transaction_id != request.transaction_id
                        or recheck.amount_micros != request.estimated_cost_micros
                    ):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Idempotency key '{request.reservation_key}' was previously reserved with conflicting "
                                f"parameters (tx={recheck.transaction_id}, amount={recheck.amount_micros})"
                            ),
                        ) from None
                    return BudgetReservation(
                        id=recheck.id,
                        tenant_id=recheck.tenant_id,
                        transaction_id=recheck.transaction_id,
                        reservation_key=recheck.reservation_key,
                        amount_micros=recheck.amount_micros,
                        status=ReservationStatus(recheck.status),
                        attempt_number=recheck.attempt_number,
                        selected_provider=recheck.selected_provider,
                        selected_model=recheck.selected_model,
                        expires_at=recheck.expires_at,
                        created_at=recheck.created_at,
                        settled_at=recheck.settled_at,
                    )
                raise

            return BudgetReservation(
                id=reservation.id,
                tenant_id=reservation.tenant_id,
                transaction_id=reservation.transaction_id,
                reservation_key=reservation.reservation_key,
                amount_micros=reservation.amount_micros,
                status=ReservationStatus.RESERVED,
                attempt_number=reservation.attempt_number,
                selected_provider=reservation.selected_provider,
                selected_model=reservation.selected_model,
                expires_at=expires_at,
                created_at=now,
                settled_at=None,
            )

    async def expand_reservation(
        self,
        tenant_id: str,
        reservation_id: str,
        additional_micros: int,
        new_provider: str | None = None,
        new_model: str | None = None,
        attempt_number: int | None = None,
    ) -> BudgetReservation:
        """Atomically increase an active reservation's amount to cover a fallback candidate."""
        if additional_micros <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Additional reservation amount must be positive",
            )
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
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Active reservation '{reservation_id}' not found for expansion",
                )

            budget_rec = await self.get_or_create_tenant_budget_record(session, tenant_id)
            current_usage = budget_rec.spent_micros + budget_rec.reserved_micros
            available = budget_rec.total_budget_micros - current_usage
            if budget_rec.hard_limit and (available < additional_micros):
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Budget limit exceeded for tenant '{tenant_id}' on fallback expansion. "
                        f"Available: {max(0, available)} micros, requested: {additional_micros} micros."
                    ),
                )

            res_rec.amount_micros += additional_micros
            if new_provider:
                res_rec.selected_provider = new_provider
            if new_model:
                res_rec.selected_model = new_model
            if attempt_number:
                res_rec.attempt_number = attempt_number

            budget_rec.reserved_micros += additional_micros
            budget_rec.updated_at = datetime.now(UTC)
            await session.commit()

            return BudgetReservation(
                id=res_rec.id,
                tenant_id=res_rec.tenant_id,
                transaction_id=res_rec.transaction_id,
                reservation_key=res_rec.reservation_key,
                amount_micros=res_rec.amount_micros,
                status=ReservationStatus(res_rec.status),
                attempt_number=res_rec.attempt_number,
                selected_provider=res_rec.selected_provider,
                selected_model=res_rec.selected_model,
                expires_at=res_rec.expires_at,
                created_at=res_rec.created_at,
                settled_at=res_rec.settled_at,
            )

    async def settle_budget(self, tenant_id: str, request: BudgetSettlementRequest) -> TransactionCostRecordSchema:
        """Atomically finalize actual expenditure, release unused headroom, and check overage."""
        if request.actual_cost_micros < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Settlement actual_cost_micros cannot be negative",
            )

        async with db_session.get_tenant_session(tenant_id) as session:
            # 1. Fetch reservation under lock
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

            # Idempotent settlement replay
            if res_rec.status == ReservationStatus.SETTLED.value:
                cost_stmt = select(TransactionCostRecord).where(
                    TransactionCostRecord.tenant_id == tenant_id,
                    TransactionCostRecord.transaction_id == res_rec.transaction_id,
                    TransactionCostRecord.attempt_number == request.attempt_number,
                )
                cost_rec = (await session.execute(cost_stmt)).scalar_one_or_none()
                if cost_rec is not None:
                    # Conflicting settlement replay check
                    if (
                        cost_rec.cost_micros != request.actual_cost_micros
                        or cost_rec.model_id != request.model_id
                        or cost_rec.provider != request.provider
                        or cost_rec.prompt_tokens != request.prompt_tokens
                        or cost_rec.completion_tokens != request.completion_tokens
                    ):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Settlement conflict: reservation '{request.reservation_id}' attempt "
                                f"{request.attempt_number} was previously settled with different parameters "
                                f"(cost={cost_rec.cost_micros}, model={cost_rec.model_id}, tokens="
                                f"{cost_rec.prompt_tokens}/{cost_rec.completion_tokens}); "
                                f"replay attempted with (cost={request.actual_cost_micros}, model={request.model_id}, "
                                f"tokens={request.prompt_tokens}/{request.completion_tokens})"
                            ),
                        )
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
                        attempt_number=cost_rec.attempt_number,
                        pricing_profile_id=cost_rec.pricing_profile_id,
                        created_at=cost_rec.created_at,
                    )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Reservation '{request.reservation_id}' is already settled",
                )

            if res_rec.status != ReservationStatus.RESERVED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Reservation '{request.reservation_id}' is in status '{res_rec.status}' "
                        "and cannot be settled"
                    ),
                )

            # 2. Lock tenant budget
            budget_rec = await self.get_or_create_tenant_budget_record(session, tenant_id)

            # 3. Check accounting drift invariant: reserved_micros must not be less than reservation amount
            if budget_rec.reserved_micros < res_rec.amount_micros:
                logger.critical(
                    "Accounting drift invariant violation",
                    tenant_id=tenant_id,
                    budget_reserved=budget_rec.reserved_micros,
                    reservation_amount=res_rec.amount_micros,
                )
                incident = AccountingIncidentRecord(
                    id=f"inc_{uuid.uuid4().hex[:16]}",
                    tenant_id=tenant_id,
                    reservation_id=res_rec.id,
                    transaction_id=res_rec.transaction_id,
                    incident_type="SETTLEMENT_DRIFT_INVARIANT_VIOLATION",
                    expected_micros=res_rec.amount_micros,
                    actual_micros=budget_rec.reserved_micros,
                    details={
                        "reservation_key": res_rec.reservation_key,
                        "attempt": request.attempt_number,
                    },
                    resolved=False,
                    created_at=datetime.now(UTC),
                )
                session.add(incident)
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Financial invariant violated: accounting drift detected for tenant '{tenant_id}'",
                )

            # 4. Handle overage in hard-limit mode
            reserved_amount = res_rec.amount_micros
            if request.actual_cost_micros > reserved_amount:
                overage = request.actual_cost_micros - reserved_amount
                available_headroom = budget_rec.total_budget_micros - (
                    budget_rec.spent_micros + budget_rec.reserved_micros
                )
                if budget_rec.hard_limit and (available_headroom < overage):
                    # Hard limit violated by overage: flag reservation and persist durable accounting incident
                    incident = AccountingIncidentRecord(
                        id=f"inc_{uuid.uuid4().hex[:16]}",
                        tenant_id=tenant_id,
                        reservation_id=res_rec.id,
                        transaction_id=res_rec.transaction_id,
                        incident_type="SETTLEMENT_OVERAGE_HARD_LIMIT_BREACH",
                        expected_micros=reserved_amount,
                        actual_micros=request.actual_cost_micros,
                        details={
                            "overage_micros": overage,
                            "available_headroom": available_headroom,
                            "model_id": request.model_id,
                            "attempt": request.attempt_number,
                        },
                        resolved=False,
                        created_at=datetime.now(UTC),
                    )
                    session.add(incident)
                    res_rec.status = ReservationStatus.RECONCILIATION_REQUIRED.value
                    await session.commit()
                    logger.warning(
                        "Actual cost exceeds reserved amount and available budget headroom under hard-limit mode",
                        tenant_id=tenant_id,
                        reservation_id=res_rec.id,
                        actual_cost=request.actual_cost_micros,
                        reserved=reserved_amount,
                        headroom=available_headroom,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=(
                            f"Actual cost ({request.actual_cost_micros} micros) exceeded reserved "
                            f"({reserved_amount} micros) and available headroom ({available_headroom} micros) "
                            f"under hard-limit policy"
                        ),
                    )

            # 5. Apply balance update
            budget_rec.reserved_micros -= reserved_amount
            budget_rec.spent_micros += request.actual_cost_micros
            budget_rec.updated_at = datetime.now(UTC)

            # 6. Mark reservation SETTLED
            now = datetime.now(UTC)
            res_rec.status = ReservationStatus.SETTLED.value
            res_rec.settled_at = now

            # 7. Insert itemized TransactionCostRecord
            cost_rec = TransactionCostRecord(
                id=f"cost_{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                transaction_id=res_rec.transaction_id,
                attempt_number=request.attempt_number,
                pricing_profile_id=request.pricing_profile_id,
                idempotency_key=request.idempotency_key or f"idem_{res_rec.id}_{request.attempt_number}",
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
                attempt_number=cost_rec.attempt_number,
                pricing_profile_id=cost_rec.pricing_profile_id,
                created_at=cost_rec.created_at,
            )

    async def release_reservation(self, tenant_id: str, reservation_id: str) -> None:
        """Release unused reservation without charging spend, checking invariants."""
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
            if budget_rec.reserved_micros < res_rec.amount_micros:
                logger.critical(
                    "Accounting drift on reservation release",
                    tenant_id=tenant_id,
                    budget_reserved=budget_rec.reserved_micros,
                    reservation_amount=res_rec.amount_micros,
                )
                incident = AccountingIncidentRecord(
                    id=f"inc_{uuid.uuid4().hex[:16]}",
                    tenant_id=tenant_id,
                    reservation_id=res_rec.id,
                    transaction_id=res_rec.transaction_id,
                    incident_type="RELEASE_DRIFT_INVARIANT_VIOLATION",
                    expected_micros=res_rec.amount_micros,
                    actual_micros=budget_rec.reserved_micros,
                    details={"reservation_key": res_rec.reservation_key},
                    resolved=False,
                    created_at=datetime.now(UTC),
                )
                session.add(incident)
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Financial invariant violated: accounting drift on release for tenant '{tenant_id}'",
                )

            budget_rec.reserved_micros -= res_rec.amount_micros
            budget_rec.updated_at = datetime.now(UTC)

            res_rec.status = ReservationStatus.RELEASED.value
            res_rec.settled_at = datetime.now(UTC)
            await session.commit()

    async def reconcile_orphaned_reservations(self, max_batch_size: int = 100) -> int:
        """Periodic background reconciliation of timed-out reservations without erasing evidence."""
        now = datetime.now(UTC)
        reconciled_count = 0

        async with db_session.get_system_session() as session:
            stmt = (
                select(BudgetReservationRecord.id, BudgetReservationRecord.tenant_id)
                .where(
                    BudgetReservationRecord.status == ReservationStatus.RESERVED.value,
                    BudgetReservationRecord.expires_at < now,
                )
                .order_by(BudgetReservationRecord.tenant_id, BudgetReservationRecord.id)
                .limit(max_batch_size)
            )
            expired_candidates = (await session.execute(stmt)).all()

        for res_id, tenant_id in expired_candidates:
            async with db_session.get_tenant_session(tenant_id) as session:
                # 1. Lock BudgetReservationRecord FIRST to maintain strict lock hierarchy
                res_stmt = (
                    select(BudgetReservationRecord)
                    .where(
                        BudgetReservationRecord.id == res_id,
                        BudgetReservationRecord.tenant_id == tenant_id,
                        BudgetReservationRecord.status == ReservationStatus.RESERVED.value,
                    )
                    .with_for_update()
                )
                res_rec = (await session.execute(res_stmt)).scalar_one_or_none()
                if res_rec is None or res_rec.status != ReservationStatus.RESERVED.value:
                    continue

                # 2. Lock TenantBudgetRecord SECOND under established reservation lock
                budget_rec = await self.get_or_create_tenant_budget_record(session, tenant_id)

                if budget_rec.reserved_micros >= res_rec.amount_micros:
                    budget_rec.reserved_micros -= res_rec.amount_micros
                    budget_rec.updated_at = now
                    res_rec.status = ReservationStatus.EXPIRED.value
                    res_rec.settled_at = now
                    await session.commit()
                    reconciled_count += 1
                else:
                    # Invariant violation: NEVER clamp or reset aggregate to zero!
                    # Preserve evidence and emit durable accounting incident record.
                    res_rec.status = ReservationStatus.RECONCILIATION_REQUIRED.value
                    res_rec.settled_at = now
                    incident = AccountingIncidentRecord(
                        id=f"inc_{uuid.uuid4().hex[:16]}",
                        tenant_id=tenant_id,
                        reservation_id=res_rec.id,
                        transaction_id=res_rec.transaction_id,
                        incident_type="ORPHAN_RECONCILIATION_DRIFT",
                        expected_micros=res_rec.amount_micros,
                        actual_micros=budget_rec.reserved_micros,
                        details={
                            "reservation_key": res_rec.reservation_key,
                            "reason": "reserved_micros in tenant budget is less than expired reservation amount",
                        },
                        resolved=False,
                        created_at=now,
                    )
                    session.add(incident)
                    await session.commit()
                    logger.critical(
                        "Drift detected in orphaned reservation reconciliation; preserved evidence",
                        tenant_id=tenant_id,
                        reservation_id=res_rec.id,
                        budget_reserved=budget_rec.reserved_micros,
                        reservation_amount=res_rec.amount_micros,
                    )

        if reconciled_count > 0:
            logger.info("Reconciled orphaned budget reservations", count=reconciled_count)

        return reconciled_count

    async def calculate_cost_for_model(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> int:
        """Lookup active pricing profile via authoritative PricingService and calculate cost in micros."""
        pricing_profile = await pricing_service.get_active_pricing_profile(model_id)
        return pricing_service.calculate_cost_micros(
            pricing_profile,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )


budget_manager_service = BudgetManagerService()
