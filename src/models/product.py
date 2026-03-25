from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from src.database import Base
from src.models.tenant import Tenant  # ← ADD THIS

class Product(Base):
    """
    Each client's product/stock catalog.
    One tenant can have thousands of products.
    """
    __tablename__ = "products"

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)

    name             = Column(String, nullable=False)
    sku              = Column(String, nullable=True)
    description      = Column(Text, nullable=True)
    category         = Column(String, nullable=True)

    price            = Column(Float, nullable=True)
    currency         = Column(String, default="LKR")
    stock_quantity   = Column(Integer, default=0)
    is_available     = Column(Boolean, default=True)

    sizes_available  = Column(String, nullable=True)
    colors_available = Column(String, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
