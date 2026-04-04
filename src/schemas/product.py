# src/schemas/agent.py
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class ProductSchema(BaseModel):
    id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None

    name: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None

    price: Optional[float] = None
    currency: str = "LKR"
    stock_quantity: int = 0
    is_available: bool = True

    sizes_available: Optional[str] = None
    colors_available: Optional[str] = None

    updated_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }
    
class ProductGetSchema(ProductSchema):
    id:               Optional[UUID] = None
    tenant_id:        Optional[UUID] = None
    name:             str
    sku:              Optional[str]   = None
    description:      Optional[str]  = None
    category:         Optional[str]  = None
    price:            Optional[float] = None
    currency:         str             = "LKR"
    stock_quantity:   int             = 0
    is_available:     bool            = True
    sizes_available:  Optional[str]  = None
    colors_available: Optional[str]  = None
    updated_at:       Optional[datetime]   = None

class ProductCreate(BaseModel):
    name: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: str = "LKR"
    stock_quantity: int = 0
    is_available: bool = True
    sizes_available: Optional[str] = None
    colors_available: Optional[str] = None


class ProductUpdate(ProductSchema):
    name:             Optional[str]   = None
    sku:              Optional[str]   = None
    description:      Optional[str]  = None
    category:         Optional[str]  = None
    price:            Optional[float] = None
    currency:         Optional[str]  = None
    stock_quantity:   Optional[int]  = None
    is_available:     Optional[bool] = None
    sizes_available:  Optional[str]  = None
    colors_available: Optional[str]  = None


