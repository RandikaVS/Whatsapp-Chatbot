# src/services/message_store.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import AsyncSessionLocal
from src.models.Conversation import Conversation
from src.models.Message import Message
import logging

logger = logging.getLogger(__name__)


async def get_or_create_conversation(
    db: AsyncSession,
    tenant_id: str,
    customer_phone: str,
    customer_name: str = None
) -> Conversation:
    """
    Finds the existing conversation for this customer, or creates
    a new one if this is their first message to this business.

    We always check before inserting to avoid duplicate conversations
    for the same (tenant_id, customer_phone) pair. In a high-traffic
    scenario you might use INSERT ... ON CONFLICT DO NOTHING here,
    but for most SaaS deployments a simple select-then-insert is fine.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.customer_phone == customer_phone
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        # First time this customer has messaged this business
        conv = Conversation(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            customer_name=customer_name
        )
        db.add(conv)
        await db.flush()  # assigns the UUID without committing yet,
                          # so we can use conv.id immediately

    elif customer_name and not conv.customer_name:
        # Update name if we didn't have it before
        conv.customer_name = customer_name

    return conv


async def save_message(
    tenant_id: str,
    customer_phone: str,
    role: str,
    content: str,
    wa_message_id: str = None,
    message_type: str = "text",
    tokens_used: int = 0,
    customer_name: str = None
) -> Message | None:
    """
    Saves a single message to the database and returns the saved object.

    Call this twice per conversation turn:
      1. When the customer's message arrives (role="user")
      2. After the AI generates a reply (role="assistant")

    The database trigger automatically updates conversation.message_count
    and conversation.last_message_at — you don't need to do that here.
    """
    try:
        async with AsyncSessionLocal() as db:
            # Get or create the parent conversation
            conv = await get_or_create_conversation(
                db, tenant_id, customer_phone, customer_name
            )

            # Build the message object
            msg = Message(
                conversation_id=conv.id,
                role=role,
                content=content,
                message_type=message_type,
                wa_message_id=wa_message_id,  # None for AI replies
                tokens_used=tokens_used
            )
            db.add(msg)

            # One commit saves both the conversation (if new) and the message.
            # The database trigger fires here and updates message_count.
            await db.commit()
            await db.refresh(msg)

            logger.debug("Saved message | conv=%s | role=%s | tokens=%s",
                         conv.id, role, tokens_used)

            return msg

    except Exception as e:
        # We catch here rather than letting it propagate because a database
        # logging failure should never prevent the bot from replying.
        # The customer's experience comes first; logging is secondary.
        logger.error("Failed to save message for %s: %s", customer_phone, e)
        return None