from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship,mapped_column
from datetime import datetime
import uuid
from src.database import Base
from src.models.tenant import Tenant  # ← ADD THIS

class Product(Base):

    __tablename__ = "products"

    id        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)

    name             = mapped_column(String, nullable=False)
    sku              = mapped_column(String, nullable=True)
    description      = mapped_column(Text, nullable=True)
    category         = mapped_column(String, nullable=True)

    price            = mapped_column(Float, nullable=True)
    currency         = mapped_column(String, default="LKR")
    stock_quantity   = mapped_column(Integer, default=0)
    is_available     = mapped_column(Boolean, default=True)

    sizes_available  = mapped_column(String, nullable=True)
    colors_available = mapped_column(String, nullable=True)

    updated_at = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def product_to_dict(p: Product) -> dict:
        return {
            "id":               str(p.id),
            "tenant_id":        str(p.tenant_id),
            "name":             p.name,
            "sku":              p.sku,
            "description":      p.description,
            "category":         p.category,
            "price":            float(p.price) if p.price is not None else None,
            "currency":         p.currency,
            "stock_quantity":   p.stock_quantity,
            "is_available":     p.is_available,
            "sizes_available":  p.sizes_available,
            "colors_available": p.colors_available,
            "updated_at":       p.updated_at.isoformat() if p.updated_at else None,
        }
