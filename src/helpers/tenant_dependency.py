# src/helpers/tenant_dependency.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.helpers.security import decode_token
from src.models.tenant import Tenant
from src.database import get_db
import uuid

bearer_scheme = HTTPBearer(
    scheme_name="Tenant Bearer Token",
    description="Paste the access_token from POST /api/tenant/auth/signin"
)


async def get_current_tenant(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> Tenant:
    """
    The single dependency that protects all tenant-facing routes.

    It does three things in sequence:
    1. Decodes and validates the JWT signature and expiry
    2. Confirms this is a 'tenant' type token (not an admin token)
    3. Fetches the tenant from the database and confirms they're still active

    If any step fails, FastAPI returns 401 before the route function runs.
    This means every protected route is secured by just adding
    Depends(get_current_tenant) to its parameters — one line of protection.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(credentials.credentials)

        # Reject admin tokens on tenant routes — this is the security boundary
        # that prevents an admin JWT from being used to access client data
        if payload.get("type") != "tenant":
            raise credentials_exception

        tenant_id = payload.get("sub")
        if not tenant_id:
            raise credentials_exception

    except ValueError:
        raise credentials_exception

    # Fetch the tenant directly by their UUID
    # No email lookup, no bridge function — the ID is the identity
    result = await db.execute(
        select(Tenant).where(
            Tenant.id == uuid.UUID(tenant_id),
            Tenant.is_active == True
        )
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant account not found or deactivated"
        )

    return tenant