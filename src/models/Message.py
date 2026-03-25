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

class Message(Base):
    """
    A single message bubble in a conversation.

    Every piece of text that flows through your system gets saved here —
    both what the customer sent and what the AI replied. This is your
    audit trail, your analytics source, and your dashboard feed.

    The wa_message_id column deserves special attention. It stores the
    unique ID that Meta assigns to every message (looks like "wamid.HBgL...").
    We put a UNIQUE constraint on it, which means if Meta delivers the same
    message twice (which happens — they guarantee "at least once" delivery),
    the second INSERT will fail with a unique violation rather than silently
    creating a duplicate. Your deduplication logic catches this before
    it even gets to the database, but the constraint is a safety net.
    """
    __tablename__ = "messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Foreign key back to the conversation this message belongs to.
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False
    )

    # "user" means the customer sent this.
    # "assistant" means the AI (Gemini/OpenAI) generated this.
    # We use these exact strings because they match the role names in the
    # AI API — so when you build the history list for the AI context,
    # you can use these values directly without any mapping.
    role = Column(
        String(20),
        nullable=False,
        comment="'user' = customer sent this | 'assistant' = AI generated this"
    )

    # The actual text content. We use Text (unlimited length) rather than
    # String (limited length) because AI replies can be long, and you never
    # want a message to silently truncate in your database.
    content = Column(
        Text,
        nullable=False
    )

    # The message type — text, image, audio, document, etc.
    # Defaults to "text" which covers the majority of messages.
    message_type = Column(
        String(50),
        default="text",
        nullable=False
    )

    # Meta's unique message ID — e.g. "wamid.HBgLOTQ3NTA2ODg3..."
    # UNIQUE constraint prevents duplicate processing.
    # Only populated for incoming customer messages (role = "user").
    # Outgoing AI messages get their own wamid when sent, but we
    # don't usually need to store it unless you want delivery tracking.
    wa_message_id = Column(
        String(500),
        nullable=True,
        unique=True,    # database-level uniqueness guarantee
        comment="Meta's wamid — unique per message, used for deduplication"
    )

    # URL to the media file if the message contained an image, audio, video, or document.
    # In a future version you might download and store this in S3/R2 so it
    # doesn't expire (Meta media URLs expire after 30 days).
    media_url = Column(
        String(1000),
        nullable=True
    )

    # How many AI tokens this message consumed.
    # Tracking this lets you calculate your actual AI cost per client,
    # which is essential for knowing whether your pricing is profitable.
    tokens_used = Column(
        Integer,
        default=0,
        nullable=False,
        comment="AI tokens consumed generating this message — for cost tracking"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Navigation back up to the parent conversation
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        preview = self.content[:40] + "..." if len(self.content) > 40 else self.content
        return f"<Message role={self.role} content='{preview}'>"