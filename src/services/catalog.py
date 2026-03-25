# src/services/catalog.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models import Product, Tenant


async def build_system_prompt_with_catalog(tenant: Tenant, db: AsyncSession) -> str:
    """
    Combines the tenant's custom system prompt with their live product catalog.
    
    The result is injected into the AI as its "knowledge" — so when a customer
    asks "do you have size 42 in black?", the AI reads the catalog and answers
    accurately based on real stock data.
    
    For small catalogs (< 200 products): inject everything.
    For large catalogs: use keyword search to inject only relevant products.
    """

    # Fetch all available products for this tenant
    result = await db.execute(
        select(Product).where(
            Product.tenant_id == tenant.id,
            Product.is_available == True
        ).order_by(Product.category, Product.name)
    )
    products = result.scalars().all()

    # Build the base system prompt (client's custom personality)
    base_prompt = tenant.system_prompt or f"You are a helpful support agent for {tenant.business_name}."

    if not products:
        # No products uploaded yet — AI still works, just without catalog knowledge
        return base_prompt

    # Format the catalog in a way the AI can easily read and reason about
    catalog_lines = []
    catalog_lines.append("\n\n--- PRODUCT CATALOG (LIVE STOCK DATA) ---")
    catalog_lines.append("Use this information to answer customer questions about products, availability, pricing, and sizes.")
    catalog_lines.append("Only recommend products that are marked as available.\n")

    # Group by category for cleaner reading
    current_category = None
    for p in products:
        if p.category != current_category:
            current_category = p.category
            catalog_lines.append(f"\n[{(current_category or 'General').upper()}]")

        # Build one line per product with all relevant info
        line = f"- {p.name}"
        if p.sku:
            line += f" (SKU: {p.sku})"
        if p.price:
            line += f" | Price: {p.currency} {p.price:,.0f}"
        if p.stock_quantity is not None:
            line += f" | Stock: {p.stock_quantity} units"
        if p.sizes_available:
            line += f" | Sizes: {p.sizes_available}"
        if p.colors_available:
            line += f" | Colors: {p.colors_available}"
        if p.description:
            # Keep description short in the prompt to save tokens
            line += f" | {p.description[:100]}"

        catalog_lines.append(line)

    catalog_lines.append("\n--- END OF CATALOG ---")
    catalog_lines.append("\nIMPORTANT RULES:")
    catalog_lines.append("- If a product is out of stock (Stock: 0), tell the customer honestly and offer alternatives.")
    catalog_lines.append("- If a size or color is not listed, it is not available.")
    catalog_lines.append("- Always confirm price and availability before the customer places an order.")

    return base_prompt + "\n".join(catalog_lines)


async def search_products_by_keyword(tenant_id: str, keyword: str, db: AsyncSession) -> list:
    """
    For large catalogs (500+ products), instead of injecting everything,
    search for products matching the customer's query and inject only those.
    
    Example: customer asks about "black sneakers size 42"
    → search for products matching "sneakers" or "black"
    → inject only those 5-10 products instead of the full 500-product catalog
    """
    from sqlalchemy import or_, func

    keyword_lower = f"%{keyword.lower()}%"
    result = await db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.is_available == True,
            or_(
                func.lower(Product.name).like(keyword_lower),
                func.lower(Product.category).like(keyword_lower),
                func.lower(Product.description).like(keyword_lower),
                func.lower(Product.colors_available).like(keyword_lower),
            )
        ).limit(15)  # inject max 15 matching products
    )
    return result.scalars().all()