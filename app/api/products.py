# app/api/products.py
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import Optional
import csv
import io
from app.database import get_db
from app.models import Product, Tenant

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductCreateRequest(BaseModel):
    name: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: str = "LKR"
    stock_quantity: int = 0
    sizes_available: Optional[str] = None   # "36,38,40,42"
    colors_available: Optional[str] = None  # "Black,White"


@router.post("/upload-csv/{tenant_id}")
async def upload_products_csv(
    tenant_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    The easiest way for clients to add their full catalog at once.
    
    Expected CSV format:
    name, sku, description, category, price, currency, stock_quantity, sizes_available, colors_available
    Nike Air Max 270, NK-270-BLK, Lightweight running shoe, sneakers, 12500, LKR, 15, "36,38,40,42,44", "Black,White"
    
    Tell clients: just export from their existing inventory system and upload here.
    """
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    content = await file.read()
    decoded = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    products_added = 0
    errors = []

    for i, row in enumerate(reader, start=2):  # start=2 because row 1 is header
        try:
            product = Product(
                tenant_id=tenant_id,
                name=row.get("name", "").strip(),
                sku=row.get("sku", "").strip() or None,
                description=row.get("description", "").strip() or None,
                category=row.get("category", "").strip() or None,
                price=float(row["price"]) if row.get("price") else None,
                currency=row.get("currency", "LKR").strip(),
                stock_quantity=int(row.get("stock_quantity", 0)),
                sizes_available=row.get("sizes_available", "").strip() or None,
                colors_available=row.get("colors_available", "").strip() or None,
                is_available=int(row.get("stock_quantity", 0)) > 0
            )
            db.add(product)
            products_added += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()

    return {
        "products_added": products_added,
        "errors": errors,
        "message": f"Successfully imported {products_added} products"
    }


@router.post("/add/{tenant_id}")
async def add_product(
    tenant_id: str,
    data: ProductCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Add a single product — useful for dashboard forms."""
    product = Product(tenant_id=tenant_id, **data.dict())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return {"product_id": str(product.id), "status": "created"}


@router.put("/update-stock/{product_id}")
async def update_stock(
    product_id: str,
    quantity: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Quick stock update — clients call this from their own inventory system
    via a webhook or scheduled job to keep stock levels accurate.
    """
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    product.stock_quantity = quantity
    product.is_available = quantity > 0
    await db.commit()

    return {"status": "stock updated", "product": product.name, "quantity": quantity}


@router.get("/list/{tenant_id}")
async def list_products(tenant_id: str, db: AsyncSession = Depends(get_db)):
    """Let clients see all their uploaded products from their dashboard."""
    result = await db.execute(
        select(Product).where(Product.tenant_id == tenant_id)
    )
    products = result.scalars().all()
    return {"products": [
        {
            "id": str(p.id),
            "name": p.name,
            "sku": p.sku,
            "price": p.price,
            "stock_quantity": p.stock_quantity,
            "is_available": p.is_available,
            "sizes_available": p.sizes_available,
        }
        for p in products
    ]}