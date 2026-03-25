# app/helpers/webhook.py
from app.config import settings
from app.services.session import SessionService
import logging
import httpx
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def detect_event_type(value: dict) -> str:
    if "messages" in value:
        return "message"
    if "statuses" in value:
        return "status"
    return "unknown"



async def generate_ai_reply(user_text: str, phone: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    history = await SessionService.get_history(phone)


    system_prompt = """You are a helpful customer support agent for ABC Shoes.
      Our products: sneakers, formal shoes, sandals.
      Sizes available: 36 to 46.
      Delivery: 2-3 days island wide.
      Always be friendly and reply in the same language the customer uses."""

    # Build contents list in Gemini format
    contents = []

    # Add conversation history
    for h in history:
        # Gemini uses "model" instead of "assistant"
        gemini_role = "model" if h["role"] == "assistant" else "user"
        contents.append(
            types.Content(
                role=gemini_role,
                parts=[types.Part(text=h["content"])]
            )
        )

    # Add current user message
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_text)]
        )
    )

    response = client.models.generate_content(
        model="gemini-3-flash-preview",           # correct model name (see note below)
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
        ),
    )

    reply = response.text

    # Save to Redis history
    await SessionService.append(phone, "user", user_text)
    await SessionService.append(phone, "assistant", reply)

    return reply


async def handle_status_update(value: dict):
    """
    Handles delivery status updates for messages your bot sent.
    
    The lifecycle of a message is: sent → delivered → read
    A failed status means the message never reached the recipient.
    We need to respond intelligently to failures, not just log them.
    """
    if not value.get("statuses"):
        return

    status = value["statuses"][0]
    status_type = status.get("status")   # sent | delivered | read | failed | deleted
    recipient   = status.get("recipient_id")
    message_id  = status.get("id")

    if status_type == "failed":
        errors = status.get("errors", [])
        for err in errors:
            code    = err.get("code")
            details = err.get("error_data", {}).get("details", "")

            logger.error("Message FAILED | to=%s | code=%s | detail=%s",
                         recipient, code, details)

            if code == 131047:
                # 24-hour window expired — send a template as recovery
                logger.warning("Attempting template recovery for %s", recipient)
                await send_template_message(recipient)

            elif code == 131026:
                # This number doesn't have WhatsApp — mark it in DB so client knows
                logger.warning("Number %s is not on WhatsApp — should flag in DB", recipient)
                # TODO: await TenantService.flag_invalid_number(recipient)

            elif code == 130429:
                # Rate limit hit — you're sending too fast
                logger.error("RATE LIMIT HIT — slow down sending to %s", recipient)

            elif code == 131000:
                # Generic error — usually a temporary Meta issue, safe to retry once
                logger.warning("Generic failure for %s — may retry", recipient)

    elif status_type == "deleted":
        # Customer deleted a message — you might want to note this in conversation history
        logger.info("Message %s was deleted by %s", message_id, recipient)

    elif status_type == "read":
        # Optional: update your conversation record to show the customer read it
        pricing = status.get("pricing", {})
        logger.info("Read | to=%s | billable=%s | category=%s",
                    recipient, pricing.get("billable"), pricing.get("category"))

    else:
        logger.info("Status: %s | to=%s", status_type, recipient)


async def send_template_message(
    phone: str,
    template_name: str = "hello_world",   # hello_world has no params needed
    language_code: str = "en_US",
    body_params: dict = None,
) -> bool:
    
    url = f"https://graph.facebook.com/v22.0/{settings.WHATSAPP_BUSINESS_ACCOUNT_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CHAT_USER_TOKEN}",
        "Content-Type": "application/json",
    }

    parameters = []
    if body_params:
        for param_name, param_value in body_params.items():
            parameters.append({
                "type": "text",
                "parameter_name": param_name,
                "text": str(param_value),
            })

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": parameters,
                }
            ] if parameters else [],
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        result = resp.json()

    if resp.status_code == 200 and "messages" in result:
        msg_id = result["messages"][0]["id"]
        logger.info("Template sent | to=%s | template=%s | msg_id=%s",
                    phone, template_name, msg_id)
        return True

    logger.error("Template send failed | to=%s | response=%s", phone, result)
    return False


async def send_text_message(phone: str, body: str) -> bool:

    print("==========Sending text message=========", phone)  
    url = f"https://graph.facebook.com/v22.0/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CHAT_USER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": body,
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        result = resp.json()

    if resp.status_code == 200 and "messages" in result:
        msg_id = result["messages"][0]["id"]
        logger.info("Text sent | to=%s | msg_id=%s", phone, msg_id)
        return True

    # Check for 24h window error specifically
    errors = result.get("error", {})
    code = errors.get("code") or errors.get("error_subcode")
    if code == 131047:
        logger.warning("24h window expired for %s", phone)
        return False

    logger.error("Send text failed | to=%s | response=%s", phone, result)
    return False


async def send_button_message(phone: str, body_text: str, buttons: list[dict]) -> bool:
    """
    buttons = [
        {"id": "btn_yes", "title": "Yes, confirm"},
        {"id": "btn_no",  "title": "No, cancel"},
    ]
    Max 3 buttons. Only works within 24h window.
    """
    url = f"https://graph.facebook.com/v22.0/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CHAT_USER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        result = resp.json()

    if resp.status_code == 200:
        logger.info("Buttons sent | to=%s", phone)
        return True

    logger.error("Button send failed | to=%s | %s", phone, result)
    return False


async def mark_as_read(message_id: str):
    """Sends read receipt — shows blue double ticks to the user."""
    url = f"https://graph.facebook.com/v22.0/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CHAT_USER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, headers=headers, json=payload)
    logger.debug("Marked as read: %s", message_id)

    
async def send_list_message(phone: str, header: str, body: str, button_label: str, sections: list) -> bool:
    """
    sections = [
        {
            "title": "Sneakers",
            "rows": [
                {"id": "prod_uuid_1", "title": "Nike Air Max", "description": "LKR 12,500 | Sizes: 40,42,44"},
                {"id": "prod_uuid_2", "title": "Adidas Ultra", "description": "LKR 9,800 | Colors: Black,White"},
            ]
        }
    ]
    """
    url = f"https://graph.facebook.com/v19.0/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CHAT_USER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "footer": {"text": "Reply with your selection"},
            "action": {
                "button": button_label,          # text on the list-open button (max 20 chars)
                "sections": sections,
            },
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error("send_list_message failed: %s", resp.text)
            return False
        return True
    
def extract_user_text(msg: dict) -> tuple[str, bool]:
    msg_type = msg.get("type")

    if msg_type == "text":
        return msg["text"]["body"], True

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        
        if interactive.get("type") == "list_reply":
            # User selected a product from your list
            selected = interactive["list_reply"]
            product_id = selected["id"]       # the UUID you set as row id
            product_name = selected["title"]
            # Return a structured string your AI / handler can act on
            return f"[PRODUCT_SELECTED:{product_id}:{product_name}]", True

        elif interactive.get("type") == "button_reply":
            return interactive["button_reply"]["title"], True

    return "", False

def build_product_sections(products: list) -> list:
    """Group products by category into WhatsApp list sections."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in products:
        category = (p.category or "Other").title()
        grouped[category].append(p)

    sections = []
    for category, items in grouped.items():
        rows = []
        for p in items[:10]:  # WhatsApp max 10 rows per section
            price_str = f"LKR {p.price:,.0f}" if p.price else "Price on request"
            description_parts = [price_str]
            if p.sizes_available:
                description_parts.append(f"Sizes: {p.sizes_available}")
            if p.colors_available:
                description_parts.append(f"Colors: {p.colors_available}")

            rows.append({
                "id": str(p.id),                          # you'll get this back when user selects
                "title": p.name[:24],                     # WhatsApp max 24 chars
                "description": " | ".join(description_parts)[:72],  # max 72 chars
            })
        sections.append({"title": category, "rows": rows})

    return sections[:10]  # WhatsApp max 10 sections


async def get_products_for_tenant(tenant_id: str) -> list:
    from app.models.product import Product
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_available == True,
                Product.stock_quantity > 0,
            )
            .order_by(Product.category, Product.name)
        )
        return result.scalars().all()
    
def _format_product_details(product) -> str:
    price_str = f"{product.currency} {product.price:,.0f}" if product.price else "Price on request"
    lines = [
        f"👟 *{product.name}*",
        f"",
        f"💰 Price   : {price_str}",
        f"📦 Stock   : {product.stock_quantity} units",
    ]
    if product.sizes_available:
        lines.append(f"📐 Sizes   : {product.sizes_available}")
    if product.colors_available:
        lines.append(f"🎨 Colors  : {product.colors_available}")
    if product.description:
        lines.append(f"")
        lines.append(product.description)
    return "\n".join(lines)


async def get_product_by_id(product_id: str):
    from app.models.product import Product
    async with AsyncSessionLocal() as db:
        return await db.get(Product, product_id)


async def _send_product_list(phone: str, tenant_id: str, customer_name: str = None):
    products = await get_products_for_tenant(tenant_id)
    if not products:
        await send_text_message(phone, "Sorry, no products are available right now. Check back soon!")
        return
    sections = build_product_sections(products)
    greeting = f"Hi {customer_name}! Here's " if customer_name else "Here's "
    await send_list_message(
        phone=phone,
        header="Our Products",
        body=f"{greeting}what we have in stock. Tap to browse and select:",
        button_label="View Products",
        sections=sections,
    )


async def create_order(phone: str, tenant_id: str, flow: dict) -> str:
    """Persist the order and return an order ID."""

    order = {
            "id":str("jhbbnmn"),
            "tenant_id":tenant_id,
            "customer_phone":phone,
            "product_id":"product_id",
            "product_name":flow["product_name"],
            "quantity":"1",
            "size":"size",
            "address":"address",
            "total_price":"100",
            "currency":"LKR",
            "status":"pending",
            "order_ref":1
    }

    return 100

    # from app.models.order import Order   # create this model
    # import uuid, datetime
    # order_id = f"ORD-{datetime.date.today().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    # async with AsyncSessionLocal() as db:
    #     order = Order(
    #         id=str(uuid.uuid4()),
    #         tenant_id=tenant_id,
    #         customer_phone=phone,
    #         product_id=flow["product_id"],
    #         product_name=flow["product_name"],
    #         quantity=flow.get("quantity", 1),
    #         size=flow.get("size"),
    #         address=flow.get("address"),
    #         total_price=flow.get("price", 0) * flow.get("quantity", 1),
    #         currency=flow.get("currency", "LKR"),
    #         status="pending",
    #         order_ref=order_id,
    #     )
    #     db.add(order)
    #     await db.commit()
    # return order_id