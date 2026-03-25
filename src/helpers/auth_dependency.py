# src/helpers/auth_dependency.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.helpers.security import decode_token
from src.models.admin import Admin
from src.database import get_db

# HTTPBearer automatically reads the "Authorization: Bearer <token>" header.
# It raises a 403 automatically if the header is missing entirely.
bearer_scheme = HTTPBearer()


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> Admin:
    """
    FastAPI dependency that validates the JWT on protected routes.
    
    Usage on any protected route:
        @router.get("/some-protected-route")
        async def my_route(admin: Admin = Depends(get_current_admin)):
            return {"hello": admin.name}
    
    If the token is missing, expired, or invalid, FastAPI automatically
    returns a 401 before your route function even runs.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(credentials.credentials)
        
        # Make sure this is an access token, not a refresh token
        if payload.get("type") != "access":
            raise credentials_exception
            
        admin_id: str = payload.get("sub")
        if admin_id is None:
            raise credentials_exception
            
    except ValueError:
        raise credentials_exception

    # Verify the admin still exists and is active in the database.
    # This catches cases where an admin was deactivated after their token was issued.
    result = await db.execute(
        select(Admin).where(Admin.id == admin_id)
    )
    admin = result.scalar_one_or_none()

    if admin is None:
        raise credentials_exception

    return admin