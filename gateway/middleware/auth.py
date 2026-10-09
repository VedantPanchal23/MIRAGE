"""Authentication and authoritative tenant resolution for MIRAGE.

JWTs authenticate a subject. Roles, tenant binding, active status, and API-key
ownership are resolved from PostgreSQL; no request claim or in-memory registry
is an authorization authority.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import text

from db import session as db_session
from shared.config import EnvironmentType, get_settings
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role

logger = get_logger("auth_middleware")
security_bearer = HTTPBearer(auto_error=False)
settings = get_settings()
EXEMPT_PATHS: set[str] = {"/v1/health", "/health", "/docs", "/redoc", "/openapi.json", "/metrics"}
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
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[algo],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
            },
        )
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
    return cast(dict[str, Any], payload)


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


async def resolve_jwt_context(token: str) -> AuthContext:
    """Resolve a signed JWT subject against the authoritative identity directory."""
    claims = _claims_from_access_token(token)
    # Test fixtures are isolated from runtime identity authority. pytest sets
    # ENVIRONMENT=test before importing the gateway; no credentials are seeded.
    if settings.environment == EnvironmentType.TEST:
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
    try:
        async with db_session.AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM mirage_resolve_jwt_identity(:subject, :tenant_id)"),
                {"subject": claims["sub"], "tenant_id": claims["tenant_id"]},
            )
            context = await _context_from_result(result, "jwt")
    except Exception as exc:
        logger.error("Authoritative identity lookup failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity authority unavailable"
        ) from exc
    if context is None:
        raise _unauthorized("Token subject is not an active identity for its asserted tenant")
    return context


async def resolve_api_key_context(api_key: str) -> AuthContext:
    """Resolve a hashed API key through PostgreSQL, including expiry and revocation."""
    if settings.environment == EnvironmentType.TEST:
        context = _TEST_API_KEY_REGISTRY.get(compute_sha256(api_key))
        if context is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return context
    try:
        async with db_session.AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM mirage_resolve_api_credential(:key_hash)"),
                {"key_hash": compute_sha256(api_key)},
            )
            context = await _context_from_result(result, "api_key")
    except Exception as exc:
        logger.error("Authoritative API credential lookup failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity authority unavailable"
        ) from exc
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
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


def register_api_key(api_key: str, tenant_id: str, role: Role = Role.API_CLIENT) -> str:
    """Register an isolated test fixture credential, never a runtime API key."""
    if settings.environment != EnvironmentType.TEST:
        raise RuntimeError("API keys must be provisioned by the control plane")
    key_hash = compute_sha256(api_key)
    _TEST_API_KEY_REGISTRY[key_hash] = AuthContext(
        tenant_id=tenant_id,
        role=role,
        user_id=f"test_key_{key_hash[:12]}",
        identity_id=f"test_identity_{key_hash[:12]}",
        principal_type="test_fixture",
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
    request.state.role = context.role.value
    return context


async def get_current_tenant(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> str:
    """Return the tenant bound by authoritative identity resolution."""
    return auth.tenant_id
