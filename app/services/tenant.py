# app/services/tenant.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.Tenant import Tenant
from app.database import AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)


async def get_tenant_by_phone_number_id(phone_number_id: str) -> Tenant | None:
    """
    The most critical lookup in the entire system.
    
    When a WhatsApp message arrives, Meta tells us WHICH phone number
    received it via metadata.phone_number_id (e.g. "943077932232321").
    We use that to find which of your business clients owns that number,
    so we can load their system prompt, AI model, and product catalog.
    
    Returns None if no tenant is registered with this phone number,
    which can happen during development when you haven't yet called
    the connect-whatsapp endpoint for a tenant.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Tenant).where(
                Tenant.wa_phone_number_id == phone_number_id,
                Tenant.is_active == True
            )
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            logger.warning(
                "No active tenant found for phone_number_id=%s. "
                "Did you call /api/onboard/connect-whatsapp?",
                phone_number_id
            )

        return tenant