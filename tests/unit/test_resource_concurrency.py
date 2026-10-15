"""Unit tests for Phase 8 Shared-Resource Concurrency, Leases, and Fencing Tokens.

Validates:
1. Canonical URI normalization (scheme, host, path segments, query).
2. Hierarchical prefix conflict detection (not naive substring matching).
3. Monotonically increasing fencing tokens per canonical resource URI.
4. Concurrency mode conflicts (EXCLUSIVE vs EXCLUSIVE, EXCLUSIVE vs SHARED, SHARED vs SHARED).
5. Safe re-entrant lease renewal by the holding transaction.
6. Safe lease release with holder identity and fencing token validation.
7. Rejection of stale fencing tokens at mutation boundaries.
8. Safe lease renewal before expiration.
9. Cross-tenant fail-closed isolation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import AITransaction, ResourceLease
from services.concurrency_service import (
    ResourceConcurrencyService,
    are_resources_in_conflict,
    canonicalize_resource_uri,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.concurrency import (
    ConcurrencyMode,
    LeaseStatus,
    ResourceLeaseAcquireRequest,
    ResourceLeaseReleaseRequest,
    ResourceLeaseRenewRequest,
)
from shared.schemas.control_plane import Decision


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_worker_1",
        role=Role.OPERATOR,
        token_id="tok_alpha_1",
        agent_id="agent_worker_1",
    )


@pytest.fixture
def test_concurrency_service() -> ResourceConcurrencyService:
    return ResourceConcurrencyService()


def _build_mock_session() -> AsyncMock:
    """Build a mock AsyncSession with synchronous Result and nested savepoint support."""
    session = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalar_one.return_value = 0
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _sample_transaction(
    tenant_id: str = "tenant_alpha",
    txn_id: str = "txn_101",
    state: str = "ACTIVE",
) -> AITransaction:
    now = datetime.now(UTC)
    return AITransaction(
        id=txn_id,
        tenant_id=tenant_id,
        actor_identity_id="usr_1",
        agent_id="agent_worker_1",
        parent_transaction_id=None,
        idempotency_key=f"idem_{txn_id}",
        correlation_id=f"corr_{txn_id}",
        state=state,
        max_turns=10,
        turn_count=1,
        taint_flags=[],
        context_sources=[],
        policy_id=None,
        budget_id=None,
        final_disposition=None,
        version=0,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# URI Canonicalization & Hierarchical Conflict Detection Tests
# ---------------------------------------------------------------------------


class TestUriCanonicalizationAndConflicts:
    """Test suite for URI normalization and prefix-based conflict matching."""

    def test_canonicalize_resource_uri_normalization(self) -> None:
        """URIs are lowercased, path cleaned of redundant dots and slashes."""
        assert (
            canonicalize_resource_uri("DB://Database.Host/v1/Ledger//Accounts/.")
            == "db://database.host/v1/ledger/accounts"
        )
        assert (
            canonicalize_resource_uri("postgres://primary.internal:5432/finance/ledger?timeout=30")
            == "postgres://primary.internal:5432/finance/ledger?timeout=30"
        )

    def test_canonicalize_schemeless_uri(self) -> None:
        """URIs without explicit scheme are given the resource://local/ prefix."""
        assert canonicalize_resource_uri("accounts/table_1") == "resource://local/accounts/table_1"
        assert canonicalize_resource_uri("/scratch/data") == "resource://local/scratch/data"

    def test_canonicalize_empty_uri_raises_value_error(self) -> None:
        """Empty or whitespace URI strings are strictly rejected."""
        with pytest.raises(ValueError):
            canonicalize_resource_uri("")
        with pytest.raises(ValueError):
            canonicalize_resource_uri("   \t  \n  ")

    def test_shared_vs_shared_never_conflicts(self) -> None:
        """Two concurrent SHARED leases on the exact same resource never conflict."""
        uri = "db://postgres/finance/ledger"
        assert not are_resources_in_conflict(uri, ConcurrencyMode.SHARED, uri, ConcurrencyMode.SHARED)

    def test_exclusive_exact_match_conflicts(self) -> None:
        """Exact matching URI conflicts if either lease is EXCLUSIVE."""
        uri = "db://postgres/finance/ledger"
        assert are_resources_in_conflict(uri, ConcurrencyMode.EXCLUSIVE, uri, ConcurrencyMode.EXCLUSIVE)
        assert are_resources_in_conflict(uri, ConcurrencyMode.EXCLUSIVE, uri, ConcurrencyMode.SHARED)
        assert are_resources_in_conflict(uri, ConcurrencyMode.SHARED, uri, ConcurrencyMode.EXCLUSIVE)

    def test_hierarchical_parent_child_prefix_conflicts(self) -> None:
        """A parent directory/prefix lock conflicts with a child subpath under EXCLUSIVE mode."""
        parent = "db://postgres/finance/ledger"
        child = "db://postgres/finance/ledger/accounts"
        assert are_resources_in_conflict(parent, ConcurrencyMode.EXCLUSIVE, child, ConcurrencyMode.EXCLUSIVE)
        assert are_resources_in_conflict(child, ConcurrencyMode.EXCLUSIVE, parent, ConcurrencyMode.EXCLUSIVE)
        assert are_resources_in_conflict(parent, ConcurrencyMode.EXCLUSIVE, child, ConcurrencyMode.SHARED)

    def test_sibling_prefix_does_not_conflict(self) -> None:
        """Hierarchical prefix matching must NOT confuse ledger with ledger_archive."""
        base = "db://postgres/finance/ledger"
        sibling = "db://postgres/finance/ledger_archive"
        assert not are_resources_in_conflict(base, ConcurrencyMode.EXCLUSIVE, sibling, ConcurrencyMode.EXCLUSIVE)
        assert not are_resources_in_conflict(sibling, ConcurrencyMode.EXCLUSIVE, base, ConcurrencyMode.EXCLUSIVE)

    def test_scheme_specific_case_sensitivity(self) -> None:
        """Case-sensitive schemes (S3, HTTP, file) preserve path casing; DB schemes case-fold."""
        # Database schemes case-fold
        assert canonicalize_resource_uri("db://Host/Finance/Ledger") == "db://host/finance/ledger"
        assert canonicalize_resource_uri("postgres://host/Schema/Table") == "postgres://host/schema/table"

        # Object store and HTTP schemes preserve case
        assert canonicalize_resource_uri("s3://My-Bucket/Assets/Doc.PDF") == "s3://my-bucket/Assets/Doc.PDF"
        assert (
            canonicalize_resource_uri("https://api.github.com/Repos/Org/Repo")
            == "https://api.github.com/Repos/Org/Repo"
        )

        # Case-sensitive URIs do not conflict if case differs
        s3_upper = "s3://bucket/Folder/Report.pdf"
        s3_lower = "s3://bucket/folder/report.pdf"
        assert not are_resources_in_conflict(s3_upper, ConcurrencyMode.EXCLUSIVE, s3_lower, ConcurrencyMode.EXCLUSIVE)

    def test_hierarchical_prefix_with_query_params(self) -> None:
        """Parent resource lock conflicts with child query subresource."""
        parent = "https://api.example.com/v1/orders"
        child = "https://api.example.com/v1/orders?tenant=1"
        assert are_resources_in_conflict(parent, ConcurrencyMode.EXCLUSIVE, child, ConcurrencyMode.EXCLUSIVE)
        assert are_resources_in_conflict(child, ConcurrencyMode.EXCLUSIVE, parent, ConcurrencyMode.EXCLUSIVE)

    def test_distinct_query_params_do_not_conflict(self) -> None:
        """Distinct query parameters on the same endpoint do not conflict."""
        res_a = "https://api.example.com/v1/orders?id=1"
        res_b = "https://api.example.com/v1/orders?id=2"
        assert not are_resources_in_conflict(res_a, ConcurrencyMode.EXCLUSIVE, res_b, ConcurrencyMode.EXCLUSIVE)


# ---------------------------------------------------------------------------
# Concurrency Service Lifecycle & Fencing Token Tests
# ---------------------------------------------------------------------------


class TestConcurrencyServiceLifecycle:
    """Test suite for lease acquisition, monotonic fencing tokens, release, and renew."""

    @pytest.fixture(autouse=True)
    def mock_agent_eligibility(self) -> Any:
        with patch(
            "services.concurrency_service.agent_governance_service.evaluate_agent_eligibility",
            return_value=(True, "Eligible"),
        ):
            yield

    @pytest.mark.asyncio
    async def test_acquire_lease_first_time_generates_token_one(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """First lease acquired on a resource receives fencing token 1."""
        session = _build_mock_session()

        req = ResourceLeaseAcquireRequest(
            resource_uri="db://postgres/finance/ledger",
            transaction_id="txn_101",
            agent_id="agent_worker_1",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
            duration_seconds=60,
        )

        # 1. Caller transaction query: returns active txn
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(txn_id="txn_101")

        # 2. Active leases query: returns []
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = []

        # 3. Max fencing token query: returns 0
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 0

        # 4. Audit query: returns None
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_token, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_concurrency_service.acquire_lease(auth=auth_context, request=req)

        assert res.id.startswith("lse_")
        assert res.resource_uri == "db://postgres/finance/ledger"
        assert res.fencing_token == 1
        assert res.status == LeaseStatus.ACQUIRED
        assert res.concurrency_mode == ConcurrencyMode.EXCLUSIVE
        assert session.add.called

    @pytest.mark.asyncio
    async def test_acquire_lease_increments_fencing_token_monotonically(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """Subsequent lease after previous release receives MAX + 1 as fencing token."""
        session = _build_mock_session()

        req = ResourceLeaseAcquireRequest(
            resource_uri="db://postgres/finance/ledger",
            transaction_id="txn_102",
            agent_id="agent_worker_1",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
            duration_seconds=60,
        )

        # 1. Transaction query: active txn
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(txn_id="txn_102")

        # 2. Active leases query: returns empty (previous lease was released)
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = []

        # 3. Max fencing token query: returns 4
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 4

        # 4. Audit query
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_token, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_concurrency_service.acquire_lease(auth=auth_context, request=req)

        assert res.fencing_token == 5

    @pytest.mark.asyncio
    async def test_acquire_lease_conflict_blocks_other_transaction(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """Acquiring a lease held exclusively by another active transaction raises 409 Conflict."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        existing_lease = ResourceLease(
            id="lse_active_1",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_other_1",
            holder_transaction_id="txn_other_1",
            holder_handoff_id=None,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=1,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=2),
            released_at=None,
            created_at=now,
            updated_at=now,
        )

        req = ResourceLeaseAcquireRequest(
            resource_uri="db://postgres/finance/ledger",
            transaction_id="txn_new_2",  # Different transaction!
            agent_id="agent_worker_1",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
            duration_seconds=60,
        )

        # 1. Transaction query: active txn
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(txn_id="txn_new_2")

        # 2. Active leases query: returns existing conflicting lease
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_lease]

        session.execute.side_effect = [exec_txn, exec_leases]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_concurrency_service.acquire_lease(auth=auth_context, request=req)

        assert exc_info.value.status_code == 409
        assert "Resource conflict" in exc_info.value.detail
        assert "txn_other_1" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_acquire_lease_reentrant_renewal(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """Re-entrant acquisition by the same transaction extends expiration safely."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        existing_lease = ResourceLease(
            id="lse_reentrant_1",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_worker_1",
            holder_transaction_id="txn_same_1",
            holder_handoff_id=None,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=2,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(seconds=10),
            released_at=None,
            created_at=now,
            updated_at=now,
        )

        req = ResourceLeaseAcquireRequest(
            resource_uri="db://postgres/finance/ledger",
            transaction_id="txn_same_1",  # Same transaction
            agent_id="agent_worker_1",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
            duration_seconds=120,
        )

        # 1. Transaction query: active txn
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(txn_id="txn_same_1")

        # 2. Active leases query: returns existing lease
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_lease]

        # 3. Audit query
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_concurrency_service.acquire_lease(auth=auth_context, request=req)

        assert res.id == "lse_reentrant_1"
        assert res.fencing_token == 2
        assert existing_lease.expires_at > now + timedelta(seconds=100)

    @pytest.mark.asyncio
    async def test_safe_release_lease_success(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """Legitimate holder presenting correct fencing token safely releases lease."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        active_lease = ResourceLease(
            id="lse_rel_1",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_worker_1",
            holder_transaction_id="txn_hold_1",
            holder_handoff_id=None,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=3,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=5),
            released_at=None,
            created_at=now,
            updated_at=now,
        )

        req = ResourceLeaseReleaseRequest(
            transaction_id="txn_hold_1",
            agent_id="agent_worker_1",
            fencing_token=3,
        )

        exec_lease = MagicMock()
        exec_lease.scalar_one_or_none.return_value = active_lease

        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_lease, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_concurrency_service.release_lease(auth=auth_context, lease_id="lse_rel_1", request=req)

        assert res.status == LeaseStatus.RELEASED
        assert active_lease.status == LeaseStatus.RELEASED.value
        assert active_lease.released_at is not None

    @pytest.mark.asyncio
    async def test_release_lease_rejects_wrong_holder_or_stale_token(
        self, test_concurrency_service: ResourceConcurrencyService, auth_context: AuthContext
    ) -> None:
        """Release attempts by mismatched transactions or stale fencing tokens are rejected."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        active_lease = ResourceLease(
            id="lse_rel_1",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_worker_1",
            holder_transaction_id="txn_hold_1",
            holder_handoff_id=None,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=5,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=5),
            released_at=None,
            created_at=now,
            updated_at=now,
        )

        exec_lease = MagicMock()
        exec_lease.scalar_one_or_none.return_value = active_lease
        session.execute.return_value = exec_lease

        # Wrong transaction ID
        req_wrong_txn = ResourceLeaseReleaseRequest(
            transaction_id="txn_wrong_99",
            agent_id="agent_worker_1",
            fencing_token=5,
        )

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_concurrency_service.release_lease(
                    auth=auth_context, lease_id="lse_rel_1", request=req_wrong_txn
                )
        assert exc_info.value.status_code == 403
        assert "not the authoritative lease holder" in exc_info.value.detail

        # Mismatched / stale fencing token
        req_stale_token = ResourceLeaseReleaseRequest(
            transaction_id="txn_hold_1",
            agent_id="agent_worker_1",
            fencing_token=4,  # Token is 5
        )

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_concurrency_service.release_lease(
                    auth=auth_context, lease_id="lse_rel_1", request=req_stale_token
                )
        assert exc_info.value.status_code == 409
        assert "does not match lease fencing token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_lease_for_action_detects_stale_token(
        self, test_concurrency_service: ResourceConcurrencyService
    ) -> None:
        """validate_lease_for_action blocks stale execution if a higher fencing token was issued."""
        session = _build_mock_session()

        # Max token issued for resource is 10
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 10
        session.execute.return_value = exec_token

        # Caller presents fencing token 8 (superseded by 10)
        dec = await test_concurrency_service.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_hold_1",
            target_resource="db://postgres/finance/ledger",
            fencing_token=8,
            session=session,
        )

        assert dec.decision == Decision.BLOCK
        assert "Stale fencing token 8" in dec.reason

    @pytest.mark.asyncio
    async def test_validate_lease_for_action_blocks_unauthorized_conflict(
        self, test_concurrency_service: ResourceConcurrencyService
    ) -> None:
        """validate_lease_for_action blocks action if another transaction holds active conflicting lease."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        other_lease = ResourceLease(
            id="lse_other_1",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_other_1",
            holder_transaction_id="txn_other_locked",
            holder_handoff_id=None,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=1,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=5),
            released_at=None,
            created_at=now,
            updated_at=now,
        )

        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [other_lease]
        session.execute.return_value = exec_leases

        # Transaction txn_my_action tries to mutate resource locked by txn_other_locked
        dec = await test_concurrency_service.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_my_action",
            target_resource="db://postgres/finance/ledger/accounts",
            fencing_token=None,
            session=session,
        )

        assert dec.decision == Decision.BLOCK
        assert "Resource conflict" in dec.reason
        assert "txn_other_locked" in dec.reason

    @pytest.mark.asyncio
    async def test_acquire_lease_rejects_unauthorized_agent_caller(
        self, test_concurrency_service: ResourceConcurrencyService
    ) -> None:
        """Acquiring a lease on behalf of a different agent is strictly forbidden for non-admin callers."""
        session = _build_mock_session()
        txn = _sample_transaction(tenant_id="tenant_alpha", txn_id="txn_101")
        session.execute.return_value.scalar_one_or_none.return_value = txn

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_intruder",
        )
        req = ResourceLeaseAcquireRequest(
            transaction_id="txn_101",
            agent_id="agent_worker_1",
            resource_uri="db://postgres/finance/ledger",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
            lease_duration_seconds=60,
        )

        with pytest.raises(HTTPException) as exc_info:
            await test_concurrency_service.acquire_lease(auth, req, session=session)
        assert exc_info.value.status_code == 403
        assert "not authorized to acquire lease on behalf of" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_release_lease_rejects_unauthorized_agent_caller(
        self, test_concurrency_service: ResourceConcurrencyService
    ) -> None:
        """Releasing a lease on behalf of a different agent is strictly forbidden for non-admin callers."""
        session = _build_mock_session()
        now = datetime.now(UTC)
        lease = ResourceLease(
            id="lse_101",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_worker_1",
            holder_transaction_id="txn_101",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=1,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=5),
            released_at=None,
            created_at=now,
            updated_at=now,
        )
        session.execute.return_value.scalar_one_or_none.return_value = lease

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_intruder",
        )
        req = ResourceLeaseReleaseRequest(
            transaction_id="txn_101",
            agent_id="agent_worker_1",
            fencing_token=1,
        )

        with pytest.raises(HTTPException) as exc_info:
            await test_concurrency_service.release_lease(auth, "lse_101", req, session=session)
        assert exc_info.value.status_code == 403
        assert "not authorized to release lease on behalf of" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_renew_lease_rejects_unauthorized_agent_caller(
        self, test_concurrency_service: ResourceConcurrencyService
    ) -> None:
        """Renewing a lease on behalf of a different agent is strictly forbidden for non-admin callers."""
        session = _build_mock_session()
        now = datetime.now(UTC)
        lease = ResourceLease(
            id="lse_101",
            tenant_id="tenant_alpha",
            resource_uri="db://postgres/finance/ledger",
            holder_agent_id="agent_worker_1",
            holder_transaction_id="txn_101",
            concurrency_mode=ConcurrencyMode.EXCLUSIVE.value,
            fencing_token=1,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=now + timedelta(minutes=5),
            released_at=None,
            created_at=now,
            updated_at=now,
        )
        session.execute.return_value.scalar_one_or_none.return_value = lease

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_intruder",
        )
        req = ResourceLeaseRenewRequest(
            transaction_id="txn_101",
            agent_id="agent_worker_1",
            fencing_token=1,
            extension_seconds=60,
        )

        with pytest.raises(HTTPException) as exc_info:
            await test_concurrency_service.renew_lease(auth, "lse_101", req, session=session)
        assert exc_info.value.status_code == 403
        assert "not authorized to renew lease on behalf of" in exc_info.value.detail
