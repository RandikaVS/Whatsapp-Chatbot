# app/services/conversation.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Conversation
from app.database import AsyncSessionLocal


async def get_or_create_conversation(phone: str, tenant_id: str) -> Conversation:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation).where(
                Conversation.customer_phone == phone,
                Conversation.tenant_id == tenant_id
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            conv = Conversation(customer_phone=phone, tenant_id=tenant_id)
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
        return conv


async def is_human_takeover_active(phone: str, tenant_id: str) -> bool:
    """
    If a human agent has taken over this conversation, the bot
    should stay completely silent — don't generate any AI reply.
    """
    conv = await get_or_create_conversation(phone, tenant_id)
    return conv.is_human_takeover


# This would be called from your dashboard API when a client clicks "Take Over"
async def set_human_takeover(phone: str, tenant_id: str, active: bool):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation).where(
                Conversation.customer_phone == phone,
                Conversation.tenant_id == tenant_id
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            conv.is_human_takeover = active
            await db.commit()