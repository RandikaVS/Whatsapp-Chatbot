# src/api/products.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional
import csv
import io
import logging

from src.database import get_db
from src.models.product import Product
from src.helpers.tenant_dependency import get_current_tenant
from src.models.tenant import Tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
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


class ProductUpdate(BaseModel):
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

async def get_current_tenant_test(db):

    result = await db.execute(
        select(Tenant).where(
            Tenant.email == 'test@abcshoes.lk',
        )
    )
    tenant = result.scalar_one_or_none()
    return tenant



@router.get("/list")
async def list_products(
    db:     AsyncSession = Depends(get_db),
):

    tenant = await get_current_tenant_test(db)
    
    result = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant.id)
        .order_by(Product.category, Product.name)
    )
    products = result.scalars().all()
    return {"products": [product_to_dict(p) for p in products]}



@router.post("/add", status_code=status.HTTP_201_CREATED)
async def add_product(
    data:   ProductCreate,
    db:     AsyncSession = Depends(get_db),
):
    
    tenant = await get_current_tenant_test(db)


    product = Product(
        tenant_id        = tenant.id,
        name             = data.name.strip(),
        sku              = data.sku.strip()              if data.sku              else None,
        description      = data.description.strip()      if data.description      else None,
        category         = data.category.strip().lower() if data.category         else None,
        price            = data.price,
        currency         = data.currency,
        stock_quantity   = data.stock_quantity,
        is_available     = data.is_available and data.stock_quantity > 0,
        sizes_available  = data.sizes_available.strip()  if data.sizes_available  else None,
        colors_available = data.colors_available.strip() if data.colors_available else None,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    logger.info("Product added: %s by tenant %s", product.name, tenant.id)
    return {"product": product_to_dict(product), "status": "created"}



@router.put("/{product_id}")
async def update_product(
    product_id: str,
    data:       ProductUpdate,
    db:         AsyncSession = Depends(get_db),
):
    tenant = await get_current_tenant_test(db)

    import uuid as uuid_module

    result = await db.execute(
        select(Product).where(
            Product.id        == uuid_module.UUID(product_id),
            Product.tenant_id == tenant.id  # security: tenant can only edit their own products
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # Apply only the fields that were actually sent
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if isinstance(value, str) and field not in ('currency',):
            value = value.strip() if value else None
        setattr(product, field, value)

    # Keep is_available in sync with stock_quantity
    if 'stock_quantity' in updates and product.stock_quantity == 0:
        product.is_available = False

    await db.commit()
    await db.refresh(product)

    logger.info("Product updated: %s by tenant %s", product.name, tenant.id)
    return {"product": product_to_dict(product), "status": "updated"}



@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    db:         AsyncSession = Depends(get_db),
):
    tenant = await get_current_tenant_test(db)

    import uuid as uuid_module

    result = await db.execute(
        select(Product).where(
            Product.id        == uuid_module.UUID(product_id),
            Product.tenant_id == tenant.id
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    product_name = product.name
    await db.delete(product)
    await db.commit()

    logger.info("Product deleted: %s by tenant %s", product_name, tenant.id)
    return {"status": "deleted", "product_name": product_name}


# ── POST /api/products/upload-csv ─────────────────────────────────────────────

@router.post("/upload-csv")
async def upload_products_csv(
    file:   UploadFile      = File(...),
    db:     AsyncSession    = Depends(get_db),
):
    tenant = await get_current_tenant_test(db)

    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .csv file"
        )

    content = await file.read()
    decoded = content.decode("utf-8-sig")  # utf-8-sig handles BOM from Excel exports
    reader  = csv.DictReader(io.StringIO(decoded))

    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file appears to be empty"
        )

    products_added = 0
    errors         = []

    for i, row in enumerate(reader, start=2):  # start=2 because row 1 is the header
        try:
            name = row.get("name", "").strip()
            if not name:
                errors.append(f"Row {i}: name is required — row skipped")
                continue

            price_raw = row.get("price", "").strip()
            price     = float(price_raw) if price_raw else None

            stock_raw     = row.get("stock_quantity", "0").strip()
            stock_quantity = int(stock_raw) if stock_raw else 0

            product = Product(
                tenant_id        = tenant.id,
                name             = name,
                sku              = row.get("sku",              "").strip() or None,
                description      = row.get("description",      "").strip() or None,
                category         = row.get("category",         "").strip().lower() or None,
                price            = price,
                currency         = row.get("currency",         "LKR").strip() or "LKR",
                stock_quantity   = stock_quantity,
                is_available     = stock_quantity > 0,
                sizes_available  = row.get("sizes_available",  "").strip() or None,
                colors_available = row.get("colors_available", "").strip() or None,
            )
            db.add(product)
            products_added += 1

        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()

    logger.info("CSV import: %d products added for tenant %s", products_added, tenant.id)

    return {
        "products_added": products_added,
        "errors":         errors,
        "message":        f"Successfully imported {products_added} products"
    }


# ── GET /api/products/csv-template ────────────────────────────────────────────

@router.get("/csv-template")
async def download_csv_template():
    """
    Returns a sample CSV file the client can download, fill in,
    and upload. This removes the guesswork about column names.
    """
    from fastapi.responses import StreamingResponse

    rows = [
        "name,sku,description,category,price,currency,stock_quantity,sizes_available,colors_available",
        'Nike Air Max 270,NK-AM270-BLK,"Lightweight everyday runner",sneakers,12500,LKR,15,"36,38,40,42,44","Black,White"',
        'Adidas Stan Smith,AD-SS-WHT,"Classic court sneaker",sneakers,9800,LKR,8,"37,38,39,40,41,42","White,Green"',
        'Oxford Formal Brogue,OX-BRG-BRN,"Genuine leather dress shoe",formal,18500,LKR,0,"40,41,42,43,44","Brown,Black"',
    ]
    content = "\n".join(rows)

    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=product_template.csv"}
    )