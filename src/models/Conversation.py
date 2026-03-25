# src/models/conversation.py
from sqlalchemy import (
    Column, String, Boolean, Integer, Text,
    DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from src.database import Base


class Conversation(Base):
    """
    Represents the ongoing chat thread between one customer phone number
    and one tenant's WhatsApp bot.

    A conversation is created the first time a customer messages a tenant,
    and it persists forever — even across days and sessions. This is how
    your dashboard can show "Sahan has sent 47 messages over 3 weeks".

    The is_human_takeover flag is the pause button for the AI. When a
    client's staff member wants to reply manually, they flip this to True
    from the dashboard. The bot checks this flag before every reply and
    goes silent when it's True.
    """
    __tablename__ = "conversations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique ID for this conversation thread"
    )

    # Which business does this conversation belong to?
    # If the tenant is deleted, all their conversations go with them (CASCADE).
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        comment="The business client who owns this WhatsApp number"
    )

    # The end customer's WhatsApp number — e.g. "94750688759"
    # This is the human talking to the bot, not the business.
    customer_phone = Column(
        String(20),
        nullable=False,
        comment="WhatsApp number of the end customer (with country code, no +)"
    )

    # WhatsApp sometimes provides the customer's display name from their profile.
    # We store it here so the dashboard can show "Sahan Randika" instead of just a number.
    customer_name = Column(
        String(200),
        nullable=True,
        comment="Display name from WhatsApp profile, if available"
    )

    # When True, the AI stays completely silent and a human agent replies manually.
    # The bot checks this before every process_and_reply call.
    is_human_takeover = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="When True, the AI is paused and a human agent is responding"
    )

    # Denormalized count — we keep this updated so the dashboard can show
    # "47 messages" without having to COUNT(*) the messages table every time.
    # This is a performance optimisation that matters when you have thousands of clients.
    message_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Cached count of messages — updated on every new message"
    )

    # These two timestamps are very useful for the dashboard:
    # started_at tells you when the customer first made contact.
    # last_message_at lets you sort conversations by most recent activity.
    started_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    last_message_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # SQLAlchemy relationship — lets you write conversation.messages to get
    # all messages, and message.conversation to navigate back up.
    # lazy="select" means messages are only fetched when you actually access the attribute.
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",   # delete messages when conversation is deleted
        order_by="Message.created_at",  # always in chronological order
    )

    def __repr__(self):
        return f"<Conversation tenant={self.tenant_id} phone={self.customer_phone} msgs={self.message_count}>"


