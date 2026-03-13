from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.database import Base

class Tenant(Base):
    """One row = one business client using your SaaS."""
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Business identity
    business_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    api_key = Column(String, unique=True, nullable=False)  # their secret key
    
    # WhatsApp connection
    wa_phone_number_id = Column(String, nullable=True)    # from Meta
    wa_access_token = Column(String, nullable=True)        # their Meta token
    wa_verify_token = Column(String, nullable=True)        # for webhook verification
    
    # AI personality — this is what makes each bot unique per client
    system_prompt = Column(Text, nullable=True)
    ai_model = Column(String, default="gemini-2.0-flash")
    language = Column(String, default="en")
    
    # Plan limits
    plan = Column(String, default="starter")
    monthly_message_limit = Column(Integer, default=1000)
    messages_used = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    products = relationship("Product", back_populates="tenant")