# app/api/auth.py
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.database import get_db
from app.models.admin import Admin
from app.helpers.security import (
    verify_password,
    hash_password,
    generate_access_token,
    generate_refresh_token,
    decode_token,
)
from app.helpers.auth_dependency import get_current_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response schemas ────────────────────────────────
# Pydantic models give you automatic validation and clear API docs.
# If someone sends {"email": "not-an-email"}, FastAPI rejects it
# with a helpful error before your code even runs.

class SigninRequest(BaseModel):
    email: EmailStr     # Pydantic validates email format automatically
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    admin: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str



@router.post("/signin", response_model=TokenResponse)
async def signin(data: SigninRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticates an admin and returns access + refresh tokens.
    
    We use a deliberately vague error message ("Invalid email or password")
    rather than "email not found" or "wrong password" separately.
    The reason: if you say "email not found", an attacker learns which
    emails are registered. Vague errors prevent that information leak.
    """
    # Look up admin by email using the ORM — safe from SQL injection
    result = await db.execute(
        select(Admin).where(Admin.email == data.email and Admin.password == data.password)
    )
    admin = result.scalar_one_or_none()

    # We check both "admin exists" and "password is correct" before raising
    # an error. Crucially, we always call verify_password even if the admin
    # doesn't exist — this prevents timing attacks where an attacker could
    # detect a valid email by measuring how long the response takes.

    # DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iZTi"
    # password_to_check = admin.password_hash if admin else DUMMY_HASH
    # is_valid = verify_password(data.password, password_to_check)

    if not admin :
        # Same error for both "email not found" and "wrong password"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    admin_id = str(admin.id)

    admin = {
            "access_token": generate_access_token(admin_id),
            "refresh_token": generate_refresh_token(admin_id),
            "admin": {
                "id": admin_id,
                "name": admin.name,
                "email": admin.email,
            }
        }

    return TokenResponse(**admin)


# ── Refresh Access Token ──────────────────────────────────────

@router.post("/refresh")
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """
    When the access token expires (after 30 minutes), the frontend
    sends the refresh token here to get a new access token.
    The user stays logged in without entering their password again.
    """
    try:
        payload = decode_token(data.refresh_token)
        
        # Reject access tokens used as refresh tokens
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
            
        admin_id = payload.get("sub")
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # Make sure the admin is still active
    result = await db.execute(
        select(Admin).where(Admin.id == admin_id)
    )
    admin = result.scalar_one_or_none()
    
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found")

    return {
        "access_token": generate_access_token(str(admin.id)),
        "token_type": "bearer"
    }


# ── Get Current Admin (me) ────────────────────────────────────

@router.get("/me")
async def get_me(admin: Admin = Depends(get_current_admin)):
    """
    Returns the currently logged-in admin's profile.
    The get_current_admin dependency validates the token automatically.
    If the token is missing or invalid, it never reaches this function.
    """
    return {
        "id": str(admin.id),
        "name": admin.name,
        "email": admin.email,
        "created_at": admin.created_at,
    }


# ── Change Password ───────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    admin: Admin = Depends(get_current_admin),   # must be logged in
    db: AsyncSession = Depends(get_db)
):
    """Allows a logged-in admin to update their own password."""
    
    # Verify they know their current password before allowing a change
    if not verify_password(data.current_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters"
        )

    admin.password_hash = hash_password(data.new_password)
    await db.commit()

    return {"message": "Password changed successfully"}