from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.database import Base

class Product(Base):
    """
    Each client's product/stock catalog.
    One tenant can have thousands of products.
    """
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # Core product info
    name = Column(String, nullable=False)           # "Nike Air Max 270"
    sku = Column(String, nullable=True)              # "NK-AIR-270-BLK-42"
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)         # "sneakers"
    
    # Stock and pricing
    price = Column(Float, nullable=True)
    currency = Column(String, default="LKR")
    stock_quantity = Column(Integer, default=0)
    is_available = Column(Boolean, default=True)
    
    # Variants — sizes, colors stored as simple strings for now
    sizes_available = Column(String, nullable=True)  # "36,38,40,42,44"
    colors_available = Column(String, nullable=True) # "Black,White,Red"
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # tenant = relationship("Tenant", back_populates="products")