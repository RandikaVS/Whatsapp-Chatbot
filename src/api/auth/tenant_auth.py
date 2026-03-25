# src/api/tenant_auth.py
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.tenant import Tenant
from src.helpers.security import verify_password, generate_access_token, generate_refresh_token
from src.helpers.tenant_dependency import get_current_tenant

router = APIRouter(prefix="/api/tenant/auth", tags=["tenant-auth"])


class TenantSigninRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/signin")
async def tenant_signin(data: TenantSigninRequest, db: AsyncSession = Depends(get_db)):
    """
    The login endpoint for business clients.
    Issues a JWT whose 'sub' is the tenant's UUID and whose 'type' is 'tenant'.
    This type distinction means admin tokens cannot be used on tenant routes
    and vice versa — an important security boundary.
    """
    result = await db.execute(
        select(Tenant).where(Tenant.email == data.email, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()

    # Same timing-attack-safe pattern as admin auth —
    # always run verify_password even if the tenant wasn't found
    dummy = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iZTi"
    password_to_check = tenant.password_hash if tenant else dummy
    is_valid = verify_password(data.password, password_to_check)

    if not tenant or not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    tenant_id = str(tenant.id)

    return {
        "access_token":  generate_access_token(tenant_id, token_type="tenant"),
        "refresh_token": generate_refresh_token(tenant_id, token_type="tenant"),
        "token_type":    "bearer",
        "tenant": {
            "id":            tenant_id,
            "business_name": tenant.business_name,
            "email":         tenant.email,
            "plan":          tenant.plan,
        }
    }


@router.get("/me")
async def tenant_me(tenant: Tenant = Depends(get_current_tenant)):
    """Returns the currently logged-in tenant's profile."""
    return {
        "id":            str(tenant.id),
        "business_name": tenant.business_name,
        "email":         tenant.email,
        "plan":          tenant.plan,
        "is_active":     tenant.is_active,
    }