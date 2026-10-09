"""Authenticated identity inspection endpoints.

MIRAGE does not expose a gateway token issuer. Production tokens originate from
the configured identity authority and authorization comes from PostgreSQL.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from gateway.middleware.auth import get_current_auth
from shared.schemas.auth import AuthContext

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


@router.get("/me", response_model=AuthContext, summary="Current authenticated identity")
async def get_current_user_info(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> AuthContext:
    """Return the identity resolved by the control plane."""
    return auth
