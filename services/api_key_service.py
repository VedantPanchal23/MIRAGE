"""API Key Lifecycle and Authentication Management Service.

Implements high-entropy cryptographic generation, prefixing, SHA-256 digest persistence,
one-time secret disclosure, rotation with bounded overlap, and instant revocation.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import ActorIdentity, ApiCredential, AuditLogRecord, Tenant
from shared.logging import get_logger
from shared.schemas.api_key import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyMetadata,
    ApiKeyRotateRequest,
)
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.tenant import TenantStatus

logger = get_logger("api_key_service")

KEY_PREFIX_LIVE = "mirage_live_"


def generate_secure_api_key(prefix: str = KEY_PREFIX_LIVE) -> tuple[str, str, str]:
    """Generate a high-entropy cryptographically secure random API key.

    Returns:
        (raw_secret, key_prefix, key_hash)
    """
    entropy = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{entropy}"
    key_prefix = raw_key[:16]
    key_hash = compute_sha256(raw_key)
    return raw_key, key_prefix, key_hash


class ApiKeyService:
    """Authoritative management service for API key credentials."""

    async def create_api_key(
        self,
        auth: AuthContext,
        req: ApiKeyCreateRequest,
        session: AsyncSession | None = None,
    ) -> ApiKeyCreatedResponse:
        """Issue a new API key, persisting only its digest and returning the secret ONCE."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key generation requires administrative privileges",
            )

        target_tenant = req.tenant_id if auth.role == Role.SUPER_ADMIN and req.tenant_id else auth.tenant_id
        if auth.role != Role.SUPER_ADMIN and req.tenant_id and req.tenant_id != auth.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant API key creation is prohibited",
            )

        now = datetime.now(UTC)
        raw_key, key_prefix, key_hash = generate_secure_api_key()

        expires_at = None
        if req.expires_in_days is not None:
            expires_at = now + timedelta(days=req.expires_in_days)

        async def _execute(s: AsyncSession) -> ApiKeyCreatedResponse:
            # 1. Verify tenant exists and is active
            tenant = await s.get(Tenant, target_tenant)
            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target tenant '{target_tenant}' not found",
                )
            if tenant.status != TenantStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot issue API key for inactive tenant (status: {tenant.status})",
                )

            # 2. Resolve or bind actor identity (API keys strictly bind to API_CLIENT machine role)
            id_stmt = (
                select(ActorIdentity)
                .where(
                    ActorIdentity.tenant_id == target_tenant,
                    ActorIdentity.role == Role.API_CLIENT.value,
                    ActorIdentity.active.is_(True),
                )
                .limit(1)
            )
            id_res = await s.execute(id_stmt)
            identity = id_res.scalar_one_or_none()
            if not identity:
                identity = ActorIdentity(
                    id=f"id_{uuid.uuid4().hex[:12]}",
                    tenant_id=target_tenant,
                    subject=f"api_client_{uuid.uuid4().hex[:8]}",
                    role=Role.API_CLIENT.value,
                    principal_type="machine",
                    active=True,
                    created_at=now,
                )
                s.add(identity)
                await s.flush()
            identity_id = identity.id

            key_id = f"key_{uuid.uuid4().hex[:12]}"
            cred = ApiCredential(
                id=key_id,
                tenant_id=target_tenant,
                identity_id=identity_id,
                name=req.name,
                key_prefix=key_prefix,
                scopes=req.scopes,
                key_hash=key_hash,
                expires_at=expires_at,
                revoked_at=None,
                created_at=now,
            )
            s.add(cred)
            await s.flush()

            # Record audit event (NEVER log the raw secret)
            await self._record_audit(
                session=s,
                tenant_id=target_tenant,
                action="API_KEY_CREATED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "key_id": key_id,
                    "name": req.name,
                    "key_prefix": key_prefix,
                    "scopes": req.scopes,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )

            logger.info("Issued new API key", tenant_id=target_tenant, key_id=key_id, prefix=key_prefix)
            meta = ApiKeyMetadata(
                id=cred.id,
                tenant_id=cred.tenant_id,
                name=cred.name,
                key_prefix=cred.key_prefix,
                scopes=cred.scopes,
                is_active=cred.is_active,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                revoked_at=cred.revoked_at,
                last_used_at=cred.last_used_at,
            )
            return ApiKeyCreatedResponse(key_metadata=meta, raw_key=raw_key, key_secret=raw_key)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(target_tenant) as s:
            return await _execute(s)

    async def list_api_keys(
        self,
        auth: AuthContext,
        tenant_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> ApiKeyListResponse:
        """List safe metadata for API keys in authorized tenant (secrets never returned)."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Listing API keys requires administrative privileges",
            )

        target_tenant = tenant_id if auth.role == Role.SUPER_ADMIN and tenant_id else auth.tenant_id
        if auth.role != Role.SUPER_ADMIN and tenant_id and tenant_id != auth.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant API key listing is prohibited",
            )

        async def _execute(s: AsyncSession) -> ApiKeyListResponse:
            stmt = (
                select(ApiCredential)
                .where(ApiCredential.tenant_id == target_tenant)
                .order_by(ApiCredential.created_at.desc())
            )
            res = await s.execute(stmt)
            creds = list(res.scalars().all())

            meta_list = [
                ApiKeyMetadata(
                    id=c.id,
                    tenant_id=c.tenant_id,
                    name=c.name,
                    key_prefix=c.key_prefix,
                    scopes=c.scopes,
                    is_active=c.is_active,
                    created_at=c.created_at,
                    expires_at=c.expires_at,
                    revoked_at=c.revoked_at,
                    last_used_at=c.last_used_at,
                )
                for c in creds
            ]
            return ApiKeyListResponse(keys=meta_list, total=len(meta_list))

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(target_tenant) as s:
            return await _execute(s)

    async def get_api_key(
        self,
        auth: AuthContext,
        key_id: str,
        session: AsyncSession | None = None,
    ) -> ApiKeyMetadata:
        """Retrieve safe metadata for a specific key."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Retrieving API key metadata requires administrative privileges",
            )

        async def _execute(s: AsyncSession) -> ApiKeyMetadata:
            cred = await s.get(ApiCredential, key_id)
            if not cred:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"API key '{key_id}' not found",
                )
            if auth.role != Role.SUPER_ADMIN and cred.tenant_id != auth.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-tenant API key access is prohibited",
                )
            return ApiKeyMetadata(
                id=cred.id,
                tenant_id=cred.tenant_id,
                name=cred.name,
                key_prefix=cred.key_prefix,
                scopes=cred.scopes,
                is_active=cred.is_active,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                revoked_at=cred.revoked_at,
                last_used_at=cred.last_used_at,
            )

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def rotate_api_key(
        self,
        auth: AuthContext,
        key_id: str,
        req: ApiKeyRotateRequest,
        session: AsyncSession | None = None,
    ) -> ApiKeyCreatedResponse:
        """Rotate an existing key, returning a new secret ONCE and handling revocation."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rotating API keys requires administrative privileges",
            )

        now = datetime.now(UTC)
        raw_key, key_prefix, key_hash = generate_secure_api_key()

        async def _execute(s: AsyncSession) -> ApiKeyCreatedResponse:
            old_cred = await s.get(ApiCredential, key_id)
            if not old_cred:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"API key '{key_id}' not found",
                )
            if auth.role != Role.SUPER_ADMIN and old_cred.tenant_id != auth.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-tenant key rotation is prohibited",
                )
            if not old_cred.is_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot rotate a key that is already revoked or expired",
                )

            # Invalidate or set grace period on old credential
            if req.immediate_revocation or req.grace_period_seconds <= 0:
                old_cred.revoked_at = now
            else:
                old_cred.expires_at = now + timedelta(seconds=req.grace_period_seconds)

            new_id = f"key_{uuid.uuid4().hex[:12]}"
            new_cred = ApiCredential(
                id=new_id,
                tenant_id=old_cred.tenant_id,
                identity_id=old_cred.identity_id,
                name=f"{old_cred.name} (Rotated)",
                key_prefix=key_prefix,
                scopes=old_cred.scopes,
                key_hash=key_hash,
                expires_at=None,
                revoked_at=None,
                created_at=now,
            )
            s.add(new_cred)
            await s.flush()

            await self._record_audit(
                session=s,
                tenant_id=old_cred.tenant_id,
                action="API_KEY_ROTATED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "old_key_id": old_cred.id,
                    "new_key_id": new_id,
                    "new_prefix": key_prefix,
                    "immediate_revocation": req.immediate_revocation,
                },
            )

            logger.info("Rotated API key", old_key_id=key_id, new_key_id=new_id, prefix=key_prefix)
            meta = ApiKeyMetadata(
                id=new_cred.id,
                tenant_id=new_cred.tenant_id,
                name=new_cred.name,
                key_prefix=new_cred.key_prefix,
                scopes=new_cred.scopes,
                is_active=new_cred.is_active,
                created_at=new_cred.created_at,
                expires_at=new_cred.expires_at,
                revoked_at=new_cred.revoked_at,
                last_used_at=new_cred.last_used_at,
            )
            return ApiKeyCreatedResponse(key_metadata=meta, raw_key=raw_key, key_secret=raw_key)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def revoke_api_key(
        self,
        auth: AuthContext,
        key_id: str,
        session: AsyncSession | None = None,
    ) -> ApiKeyMetadata:
        """Immediately revoke an API key."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Revoking API keys requires administrative privileges",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> ApiKeyMetadata:
            cred = await s.get(ApiCredential, key_id)
            if not cred:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"API key '{key_id}' not found",
                )
            if auth.role != Role.SUPER_ADMIN and cred.tenant_id != auth.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-tenant key revocation is prohibited",
                )

            cred.revoked_at = now
            await s.flush()

            await self._record_audit(
                session=s,
                tenant_id=cred.tenant_id,
                action="API_KEY_REVOKED",
                actor_id=auth.identity_id or auth.user_id,
                details={"key_id": key_id, "key_prefix": cred.key_prefix},
            )

            logger.info("Revoked API key", key_id=key_id, tenant_id=cred.tenant_id)
            return ApiKeyMetadata(
                id=cred.id,
                tenant_id=cred.tenant_id,
                name=cred.name,
                key_prefix=cred.key_prefix,
                scopes=cred.scopes,
                is_active=cred.is_active,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                revoked_at=cred.revoked_at,
                last_used_at=cred.last_used_at,
            )

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def _record_audit(
        self,
        session: AsyncSession,
        tenant_id: str,
        action: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        """Record an API key audit event without ever leaking credentials."""
        now = datetime.now(UTC)
        seq_stmt = (
            select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
            .where(AuditLogRecord.tenant_id == tenant_id)
            .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
            .limit(1)
        )
        res = await session.execute(seq_stmt)
        latest_row = res.first()
        prev_hash = latest_row[0] if latest_row and latest_row[0] is not None else ("0" * 64)
        prev_seq = latest_row[1] if latest_row and len(latest_row) > 1 and latest_row[1] is not None else 0
        seq = prev_seq + 1
        entry_id = f"aud_{uuid.uuid4().hex}"
        chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{action}:{now.isoformat()}")

        rec = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=f"sess_{tenant_id}",
            trace_id="control-plane",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="CONTROL_PLANE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=f"AUTH_{action}",
            actor_identity_id=actor_id,
            transaction_id=None,
            decision="ALLOWED",
            policy_reference="api_key_policy",
            reason=f"Credential lifecycle: {action}",
            event_payload=details,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(rec)


api_key_service = ApiKeyService()
