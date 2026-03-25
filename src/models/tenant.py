# src/models/tenant.py
from sqlalchemy import Column, String, Boolean, Integer, Text, Numeric, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from sqlalchemy.orm import relationship
import uuid
from src.database import Base


class Tenant(Base):
    __tablename__ = "tenant"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Business identity ─────────────────────────────────────────
    business_name = Column(String, nullable=False)
    email         = Column(String, nullable=False, unique=True)
    api_key       = Column(String, nullable=False, unique=True)

    # ── WhatsApp connection ───────────────────────────────────────
    wa_phone_number_id = Column(String, nullable=True)
    wa_access_token    = Column(String, nullable=True)
    wa_verify_token    = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)

    # ── Bot personality (the "My Agent" settings) ─────────────────
    # is_bot_active is the master switch. When False, the webhook
    # receives messages but process_and_reply() returns immediately.
    is_bot_active = Column(Boolean, nullable=False, default=True)

    # system_prompt is the most important field in the entire product.
    # It defines the AI's knowledge, personality, and behaviour.
    system_prompt   = Column(Text, default="You are a helpful customer support agent.")
    welcome_message = Column(Text, default="Hi! 👋 How can I help you today?")
    ai_model        = Column(String, default="gemini-2.0-flash")
    language        = Column(String, default="auto")

    # temperature controls response creativity (0.1 = precise, 1.0 = creative)
    # We use Numeric(3,1) to store values like 0.7 precisely.
    temperature = Column(Numeric(3, 1), default=0.7)

    # max_tokens caps reply length. ~400 tokens ≈ 300 words for WhatsApp.
    max_tokens = Column(Integer, default=400)

    # reply_delay_seconds adds a human-feeling pause before sending.
    reply_delay_seconds = Column(Integer, default=0)
    flow_config = Column(JSON, default=None)

    # ── Plan and usage ────────────────────────────────────────────
    plan                  = Column(String, default="starter")
    monthly_message_limit = Column(Integer, default=1000)
    messages_used         = Column(Integer, default=0)
    stripe_customer_id    = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships — these let you write tenant.products or tenant.conversations
    # src/models/Tenant.py
