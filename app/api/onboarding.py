# app/api/onboarding.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
import secrets
from app.database import get_db
from app.models import Tenant

router = APIRouter(prefix="/api/onboard", tags=["onboarding"])


class TenantRegisterRequest(BaseModel):
    business_name: str
    email: EmailStr
    plan: str = "starter"


class TenantConnectWhatsAppRequest(BaseModel):
    wa_phone_number_id: str
    wa_access_token: str


class TenantBotConfigRequest(BaseModel):
    # This is the most important config — describes the AI's personality
    system_prompt: str
    ai_model: str = "gemini-2.0-flash"
    language: str = "en"


@router.post("/register")
async def register_tenant(data: TenantRegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Step 1 of onboarding: client signs up, gets their api_key and webhook URL.
    They show this to the client on a success screen.
    """
    # Generate a unique, unguessable API key for this client
    api_key = secrets.token_urlsafe(32)
    # Each client gets their own webhook URL containing their api_key
    # This is how your system knows which client a message belongs to
    wa_verify_token = secrets.token_hex(16)

    tenant = Tenant(
        business_name=data.business_name,
        email=data.email,
        api_key=api_key,
        wa_verify_token=wa_verify_token,
        plan=data.plan,
        monthly_message_limit={"starter": 1000, "pro": 10000, "enterprise": 100000}[data.plan],
        # Default system prompt — client customises this later
        system_prompt=f"You are a helpful customer support agent for {data.business_name}. Be friendly and professional."
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    return {
        "tenant_id": str(tenant.id),
        "api_key": api_key,
        # This is the URL they paste into Meta Developer Console
        "webhook_url": f"https://yourdomain.com/webhook/{api_key}",
        "verify_token": wa_verify_token,
        "next_steps": [
            "1. Go to developers.facebook.com and create a WhatsApp app",
            f"2. Set webhook URL to: https://yourdomain.com/webhook/{api_key}",
            f"3. Set verify token to: {wa_verify_token}",
            "4. Call /api/onboard/connect-whatsapp with your phone_number_id and token",
            "5. Upload your products via /api/products/upload-csv"
        ]
    }


@router.post("/connect-whatsapp/{tenant_id}")
async def connect_whatsapp(
    tenant_id: str,
    data: TenantConnectWhatsAppRequest,
    db: AsyncSession = Depends(get_db)
):
    """Step 2: Client connects their Meta WhatsApp credentials."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    tenant.wa_phone_number_id = data.wa_phone_number_id
    tenant.wa_access_token = data.wa_access_token
    await db.commit()

    return {"status": "WhatsApp connected successfully"}


@router.put("/bot-config/{tenant_id}")
async def update_bot_config(
    tenant_id: str,
    data: TenantBotConfigRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 3: Client sets their AI personality.
    This system_prompt is what makes their bot sound like THEIR business.
    Example: "You are a support agent for Colombo Shoes. We sell sneakers and
    formal shoes. Always offer to check stock when a customer asks about a product."
    """
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    tenant.system_prompt = data.system_prompt
    tenant.ai_model = data.ai_model
    tenant.language = data.language
    await db.commit()

    return {"status": "Bot configuration updated"}