"""Authentication and authoritative tenant resolution for MIRAGE.

JWTs authenticate a subject. Roles, tenant binding, active status, and API-key
ownership are resolved from PostgreSQL; no request claim or in-memory registry
is an authorization authority.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import ActorIdentity, Agent, ApiCredential, Tenant
from shared.config import EnvironmentType, get_settings
from shared.logging import get_logger
from shared.schemas.agent import AgentStatus
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role

logger = get_logger("auth_middleware")
security_bearer = HTTPBearer(auto_error=False)
settings = get_settings()
EXEMPT_PATHS: set[str] = {
    "/v1/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/v1/auth/register-tenant",
    "/v1/billing/plans",
    "/v1/billing/webhook",
}
_TEST_API_KEY_REGISTRY: dict[str, AuthContext] = {}


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def _claims_from_access_token(
    token: str, secret_key: str | None = None, algorithm: str | None = None
) -> dict[str, Any]:
    """Verify credential cryptography and return identity-only claims."""
    key = secret_key or settings.secret_key
    algo = algorithm or settings.algorithm

    # Enforce fail-closed production and staging key configuration
    if settings.environment in (EnvironmentType.PRODUCTION, EnvironmentType.STAGING):
        if not key or key == "dev-insecure-secret-key-change-in-production-min32chars" or len(key) < 32:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication secret key is unconfigured or using insecure default in staging/production",
            )

    # Reject algorithm confusion or 'none' algorithm
    if not algo or algo.lower() == "none":
        raise _unauthorized("Unsigned tokens with 'none' algorithm are strictly prohibited")

    try:
        unverified_header = jwt.get_unverified_header(token)
        if unverified_header.get("alg", "").lower() == "none":
            raise _unauthorized("Unsigned tokens with 'none' algorithm are strictly prohibited")
        if unverified_header.get("jku") or unverified_header.get("x5u"):
            raise _unauthorized("Arbitrary key URLs (jku/x5u) in token headers are prohibited")
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed authentication token: {exc}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    try:
        decoded = jwt.decode(
            token,
            key,
            algorithms=[algo],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
            },
        )
        if not isinstance(decoded, dict):
            raise _unauthorized("Malformed JWT payload: expected object")
        payload: dict[str, Any] = decoded
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The access token expired"'},
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token signature or malformed token: {exc}",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    tenant_id = payload.get("tenant_id")
    if not tenant_id or not isinstance(tenant_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing mandatory 'tenant_id' claim",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    role_str = payload.get("role")
    if not role_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing mandatory 'role' claim",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    try:
        Role(str(role_str).lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token contains unrecognized role '{role_str}'",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized("Token is missing mandatory identity claims")

    # Validate issuer when configured in settings
    if settings.jwt_issuer:
        if "iss" not in payload:
            raise _unauthorized("Token missing mandatory 'iss' claim required by configuration")
        if payload["iss"] != settings.jwt_issuer:
            raise _unauthorized(
                f"Token issuer '{payload['iss']}' does not match trusted issuer '{settings.jwt_issuer}'"
            )

    # Validate audience when configured in settings
    if settings.jwt_audience:
        if "aud" not in payload:
            raise _unauthorized("Token missing mandatory 'aud' claim required by configuration")
        if payload["aud"] != settings.jwt_audience:
            raise _unauthorized(
                f"Token audience '{payload['aud']}' does not match expected audience '{settings.jwt_audience}'"
            )

    return payload


async def _context_from_result(result: Any, token_type: str) -> AuthContext | None:
    row = result.mappings().first()
    if row is None:
        return None
    try:
        role = Role(str(row["role"]).lower())
    except ValueError:
        logger.error("Persisted identity has invalid role", identity_id=row["identity_id"])
        return None
    return AuthContext(
        tenant_id=str(row["tenant_id"]),
        role=role,
        user_id=str(row["user_id"]),
        identity_id=str(row["identity_id"]),
        principal_type=str(row["principal_type"]),
        is_authenticated=True,
        token_type=token_type,  # type: ignore[arg-type]
    )


async def resolve_agent_context(
    token: str,
    session: AsyncSession | None = None,
    secret_key: str | None = None,
    algorithm: str | None = None,
) -> AuthContext:
    """Authoritatively verify and resolve a token for a governed agent principal.

    Enforces:
    1. Cryptographic token signature and expiration verification.
    2. Tenant binding matching asserted claims.
    3. Persisted Agent existence in asserted tenant.
    4. Authoritative Agent lifecycle status (must be ACTIVE; rejects REGISTERED, SUSPENDED, REVOKED).
    5. Persisted ActorIdentity existence and active status.
    6. Returns an AuthContext with agent_id strictly bound from PostgreSQL.
    """
    claims = _claims_from_access_token(token, secret_key=secret_key, algorithm=algorithm)
    tenant_id = claims["tenant_id"]
    agent_id = claims.get("agent_id")
    if not agent_id:
        sub = str(claims.get("sub", ""))
        if sub.startswith("agent:"):
            agent_id = sub[len("agent:") :]
        else:
            agent_id = sub

    if not agent_id:
        raise _unauthorized("Agent token missing mandatory agent identification claims")

    async def _resolve_with_session(s: AsyncSession) -> AuthContext:
        agent = await s.get(Agent, agent_id)
        if agent is None or agent.tenant_id != tenant_id:
            raise _unauthorized(f"Agent '{agent_id}' does not exist in asserted tenant '{tenant_id}'")

        if agent.status == AgentStatus.SUSPENDED.value:
            raise _unauthorized(
                f"Authenticated agent '{agent_id}' is suspended: {agent.suspension_reason or 'No reason provided'}"
            )
        if agent.status == AgentStatus.REVOKED.value or agent.revoked_at is not None:
            raise _unauthorized(
                f"Authenticated agent '{agent_id}' is permanently revoked: "
                f"{agent.revocation_reason or 'No reason provided'}"
            )
        if agent.status != AgentStatus.ACTIVE.value or not agent.active:
            raise _unauthorized(
                f"Authenticated agent '{agent_id}' is not in active state (current status: {agent.status})"
            )

        act_stmt = select(ActorIdentity).where(
            ActorIdentity.tenant_id == tenant_id,
            (ActorIdentity.agent_id == agent_id)
            | (ActorIdentity.subject == f"agent:{agent_id}")
            | (ActorIdentity.subject == agent_id),
        )
        actor_identity = (await s.execute(act_stmt)).scalar_one_or_none()
        if actor_identity is None or not actor_identity.active:
            raise _unauthorized(f"Actor identity for agent '{agent_id}' is inactive or missing")

        role_str = actor_identity.role or claims.get("role", Role.API_CLIENT.value)
        try:
            role = Role(str(role_str).lower())
        except ValueError:
            role = Role.API_CLIENT

        return AuthContext(
            tenant_id=agent.tenant_id,
            role=role,
            user_id=actor_identity.subject,
            identity_id=actor_identity.id,
            principal_type="agent",
            agent_id=agent.id,
            is_authenticated=True,
            token_type="jwt",
        )

    if session is not None:
        return await _resolve_with_session(session)

    if settings.environment == EnvironmentType.TEST and not getattr(db_session, "engine", None):
        # Fallback only for isolated offline unit tests where database engine is completely absent
        role = Role(str(claims.get("role", Role.API_CLIENT.value)).lower())
        return AuthContext(
            tenant_id=tenant_id,
            role=role,
            user_id=str(claims["sub"]),
            identity_id=f"test_identity_{agent_id}",
            principal_type="agent",
            agent_id=agent_id,
            is_authenticated=True,
            token_type="jwt",
        )

    async with db_session.AsyncSessionLocal() as s:
        return await _resolve_with_session(s)


async def resolve_jwt_context(token: str, session: AsyncSession | None = None) -> AuthContext:
    """Resolve a signed JWT subject against the authoritative identity directory."""
    claims = _claims_from_access_token(token)

    # Route agent principals to authoritative agent verifier
    if (
        claims.get("principal_type") == "agent"
        or claims.get("agent_id") is not None
        or str(claims.get("sub", "")).startswith("agent:")
    ):
        return await resolve_agent_context(token, session=session)

    # Test fixtures are isolated from runtime identity authority. pytest sets
    # ENVIRONMENT=test before importing the gateway; no credentials are seeded.
    if settings.environment == EnvironmentType.TEST and session is None:
        try:
            role = Role(str(claims.get("role", Role.API_CLIENT.value)).lower())
        except ValueError as exc:
            raise _unauthorized("Test fixture contains an invalid role") from exc
        return AuthContext(
            tenant_id=str(claims["tenant_id"]),
            role=role,
            user_id=str(claims["sub"]),
            identity_id=f"test_identity_{claims['sub']}",
            principal_type="test_fixture",
            is_authenticated=True,
            token_type="jwt",
        )

    async def _resolve_user(s: AsyncSession) -> AuthContext:
        result = await s.execute(
            text("SELECT * FROM mirage_resolve_jwt_identity(:subject, :tenant_id)"),
            {"subject": claims["sub"], "tenant_id": claims["tenant_id"]},
        )
        context = await _context_from_result(result, "jwt")
        if context is None:
            raise _unauthorized("Token subject is not an active identity for its asserted tenant")
        return context

    if session is not None:
        return await _resolve_user(session)

    try:
        async with db_session.AsyncSessionLocal() as s:
            return await _resolve_user(s)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Authoritative identity lookup failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity authority unavailable"
        ) from exc


async def resolve_api_key_context(api_key: str) -> AuthContext:
    """Resolve a hashed API key through PostgreSQL, including tenant status, expiry, and revocation."""
    key_hash = compute_sha256(api_key)

    if settings.environment == EnvironmentType.TEST:
        context = _TEST_API_KEY_REGISTRY.get(key_hash)
        if context is not None:
            return context
        # In test environment, if test registry doesn't have it, fall through to database if engine exists
        if not getattr(db_session, "engine", None):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    try:
        async with db_session.AsyncSessionLocal() as session:
            # Check tenant status first to provide clear failure semantics
            result = await session.execute(
                text("SELECT * FROM mirage_resolve_api_credential(:key_hash)"),
                {"key_hash": key_hash},
            )
            context = await _context_from_result(result, "api_key")

            if context is None:
                # Distinguish inactive tenant from invalid key if key exists
                cred_res = await session.execute(
                    select(
                        ApiCredential.tenant_id,
                        ApiCredential.revoked_at,
                        ApiCredential.expires_at,
                        ApiCredential.scopes,
                    ).where(ApiCredential.key_hash == key_hash)
                )
                cred_row = cred_res.first()
                if cred_row:
                    t_res = await session.execute(select(Tenant.status).where(Tenant.id == cred_row[0]))
                    t_status = t_res.scalar_one_or_none()
                    if t_status and t_status != "ACTIVE":
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f"Tenant '{cred_row[0]}' is {t_status.lower()}; authentication denied",
                            headers={"WWW-Authenticate": "Bearer"},
                        )

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or revoked API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Resolve scopes from ApiCredential and attach to capabilities
            cred_scopes_res = await session.execute(
                select(ApiCredential.scopes).where(ApiCredential.key_hash == key_hash)
            )
            scopes_val = cred_scopes_res.scalar_one_or_none()
            if scopes_val and isinstance(scopes_val, list):
                context.capabilities = frozenset(scopes_val)

            # Touch last_used_at timestamp
            now = datetime.now(UTC)
            await session.execute(
                text("UPDATE api_credentials SET last_used_at = :now WHERE key_hash = :key_hash"),
                {"now": now, "key_hash": key_hash},
            )
            await session.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Authoritative API credential lookup failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity authority unavailable"
        ) from exc

    return context


def create_access_token(
    tenant_id: str,
    role: Role | str = Role.API_CLIENT,
    user_id: str = "user_default",
    expires_delta: timedelta | None = None,
    secret_key: str | None = None,
    algorithm: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a local test fixture; it never establishes authorization by itself."""
    if settings.environment not in {EnvironmentType.TEST, EnvironmentType.DEVELOPMENT}:
        raise RuntimeError("Local access-token issuance is disabled outside test/development")
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": (role.value if isinstance(role, Role) else str(role)),
        "jti": f"local-{now.timestamp()}",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra_claims:
        claims.update(extra_claims)
    return str(jwt.encode(claims, secret_key or settings.secret_key, algorithm=algorithm or settings.algorithm))


def create_agent_access_token(
    tenant_id: str,
    agent_id: str,
    role: Role | str = Role.API_CLIENT,
    expires_delta: timedelta | None = None,
    secret_key: str | None = None,
    algorithm: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a local signed JWT access token bound to a governed agent principal."""
    claims: dict[str, Any] = {
        "principal_type": "agent",
        "agent_id": agent_id,
    }
    if extra_claims:
        claims.update(extra_claims)
    return create_access_token(
        tenant_id=tenant_id,
        role=role,
        user_id=f"agent:{agent_id}",
        expires_delta=expires_delta,
        secret_key=secret_key,
        algorithm=algorithm,
        extra_claims=claims,
    )


def register_api_key(
    api_key: str,
    tenant_id: str,
    role: Role = Role.API_CLIENT,
    scopes: list[str] | None = None,
) -> str:
    """Register an isolated test fixture credential, never a runtime API key."""
    if settings.environment != EnvironmentType.TEST:
        raise RuntimeError("API keys must be provisioned by the control plane")
    key_hash = compute_sha256(api_key)
    caps = frozenset(scopes if scopes is not None else ["*"])
    _TEST_API_KEY_REGISTRY[key_hash] = AuthContext(
        tenant_id=tenant_id,
        role=role,
        user_id=f"test_key_{key_hash[:12]}",
        identity_id=f"test_identity_{key_hash[:12]}",
        principal_type="test_fixture",
        capabilities=caps,
        is_authenticated=True,
        token_type="api_key",
    )
    return key_hash


def revoke_api_key(api_key: str) -> bool:
    """Revoke an isolated test fixture credential, never a runtime API key."""
    if settings.environment != EnvironmentType.TEST:
        raise RuntimeError("API keys must be revoked by the control plane")
    return _TEST_API_KEY_REGISTRY.pop(compute_sha256(api_key), None) is not None


async def decode_access_token(token: str) -> AuthContext:
    """Backward-compatible async entry point for authoritative JWT resolution."""
    return await resolve_jwt_context(token)


async def get_current_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)] = None,
) -> AuthContext:
    """Authenticate a request and bind only authoritative context to request state."""
    raw_token: str | None = None
    if credentials and credentials.credentials:
        raw_token = credentials.credentials
    elif request.headers.get("X-API-Key"):
        raw_token = request.headers.get("X-API-Key")

    if not raw_token:
        if request.url.path.rstrip("/") in EXEMPT_PATHS:
            context = AuthContext(
                tenant_id="anonymous",
                role=Role.API_CLIENT,
                user_id="anonymous",
                is_authenticated=False,
                token_type="api_key",
            )
            request.state.auth = context
            return context
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication credentials (Bearer token or API Key)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if raw_token.count(".") == 2:
        context = await resolve_jwt_context(raw_token)
    else:
        context = await resolve_api_key_context(raw_token)

    request.state.auth = context
    request.state.tenant_id = context.tenant_id
    request.state.role = context.role.value
    return context


async def get_current_tenant(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> str:
    """Return the tenant bound by authoritative identity resolution."""
    return auth.tenant_id
