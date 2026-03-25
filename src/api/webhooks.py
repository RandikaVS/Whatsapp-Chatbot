# src/api/webhook.py
from fastapi import APIRouter, Request, HTTPException, Query, BackgroundTasks, Depends
import httpx
import logging
from ..config import settings
from ..services.session import SessionService, update_customer_message_timestamp, is_within_24h_window, is_duplicate
from ..helpers.webhook import detect_event_type, generate_ai_reply, handle_status_update,send_template_message,send_text_message,send_button_message,mark_as_read,extract_user_text,send_list_message,build_product_sections,get_products_for_tenant,create_order,_send_product_list,get_product_by_id,_format_product_details
from ..database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from ..services.conversation import is_human_takeover_active, set_human_takeover
from ..services.message_store import save_message
from src.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()



@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: int = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_message(request: Request, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    try:

        data = await request.json()
        logger.info("Webhook received: %s", data)

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):

                value = change.get("value", {})

                msg_type = detect_event_type(value)

                print("Detected event type:", msg_type) 

                if msg_type == "message":
                    await _handle_incoming_message(value, bg)

                elif msg_type == "status":
                    await handle_status_update(value)

    except Exception as e:
        logger.exception("Webhook processing error: %s", e)

    # Always return 200 — Meta will retry if you return anything else
    return {"status": "ok"}


async def _handle_incoming_message(value: dict, bg: BackgroundTasks):
    print("Handling incoming message...", value)  
    msg = value["messages"][0]
    phone     = msg["from"]                          
    msg_id    = msg["id"]                          
    msg_type  = msg.get("type", "text")             
    timestamp = int(msg.get("timestamp", 0))

    if await is_duplicate(msg_id):
        logger.warning("Duplicate message ignored: %s from %s", msg_id, phone)
        return
    
    # ── Step 1: Extract the phone_number_id from metadata ──────────
    # This is YOUR WhatsApp business number's ID (not the customer's).
    # It tells you WHICH of your tenants received this message.
    # In a single-tenant setup this is always the same value,
    # but in multi-tenant you MUST look this up per message.
    phone_number_id = value.get("metadata", {}).get("phone_number_id")
    if not phone_number_id:
        logger.error("No phone_number_id in webhook metadata — cannot route message")
        return

    # ── Step 2: Look up which tenant owns this WhatsApp number ─────
    from src.services.tenant import get_tenant_by_phone_number_id
    tenant = await get_tenant_by_phone_number_id(phone_number_id)

    if not tenant:
        # No tenant registered for this number — log and ignore.
        # This is safe to ignore: it just means the number isn't
        # connected to any client in your system yet.
        logger.warning("Ignoring message — no tenant for phone_number_id=%s", phone_number_id)
        return

    # ── Step 3: Extract customer name if WhatsApp provided it ──────
    contacts = value.get("contacts", [])
    customer_name = None
    if contacts:
        customer_name = contacts[0].get("profile", {}).get("name")

    await update_customer_message_timestamp(phone)

    user_text, should_reply = extract_user_text(msg)


    logger.info("Incoming | phone=%s | type=%s | text=%s | will_reply=%s",
                phone, msg.get("type"), user_text, should_reply)

    # Always mark as read regardless of message type
    bg.add_task(mark_as_read, msg_id)

    # Only trigger AI if the message type warrants a response
    if should_reply:
        bg.add_task(process_and_reply, phone, user_text, str(tenant.id), msg_id,customer_name)


async def process_and_reply(phone: str, user_text: str, tenant_id: str, wa_message_id: str, customer_name: str = None):
    try:
        from src.services.keyword_triggers import check_keyword_triggers
        from src.services.flow import get_flow_state, set_flow_state, clear_flow_state
        from src.models.tenant import Tenant

        async with AsyncSessionLocal() as db:
            tenant = await db.get(Tenant, tenant_id)

        if not tenant:
            return

        # if await is_human_takeover_active(phone, tenant_id):
        #     return

        await save_message(phone, tenant_id, "user", user_text, wa_message_id=wa_message_id)

        # ── Keyword triggers (highest priority) ────────────────────
        # trigger_result = check_keyword_triggers(user_text)
        # if trigger_result:
        #     trigger_reply, action = trigger_result
        #     if action == "clear_history":
        #         await SessionService.clear(phone)
        #         await clear_flow_state(phone)
        #     elif action == "escalate":
        #         await set_human_takeover(phone, tenant_id, active=True)
        #     await save_message(phone, tenant_id, "assistant", trigger_reply)
        #     await send_text_message(phone, trigger_reply)
        #     return

        # ── Load current flow state ────────────────────────────────
        flow = await get_flow_state(phone)
        step = flow.get("step", "idle")

        # ── Global reset words ─────────────────────────────────────
        if user_text.strip().lower() in ["hi", "hello", "hey", "start", "menu", "help"]:
            await clear_flow_state(phone)
            step = "idle"

        # ══════════════════════════════════════════════════════════
        # STEP: idle — show main menu
        # ══════════════════════════════════════════════════════════
        if step == "idle":
            greeting = f"Hi {customer_name}! 👋" if customer_name else "Hello! 👋"
            await send_button_message(
                phone=phone,
                body_text=(
                    f"{greeting} Welcome to *{tenant.business_name}*!\n\n"
                    "How can I help you today?"
                ),
                buttons=[
                    {"id": "flow_browse",   "title": "🛍️ Browse Products"},
                    {"id": "flow_order",    "title": "📦 My Orders"},
                    {"id": "flow_support",  "title": "💬 Support"},
                ],
            )
            await set_flow_state(phone, {"step": "main_menu"})
            await save_message(phone, tenant_id, "assistant", "[Sent main menu]")
            return

        # ══════════════════════════════════════════════════════════
        # STEP: main_menu — handle button tap
        # ══════════════════════════════════════════════════════════
        if step == "main_menu":
            if user_text == "flow_browse" or "browse" in user_text.lower() or "product" in user_text.lower():
                await _send_product_list(phone, tenant_id, customer_name)
                await set_flow_state(phone, {"step": "browsing"})
                return

            elif user_text == "flow_order" or "order" in user_text.lower():
                reply = (
                    "📦 *Order Tracking*\n\n"
                    "Please share your order number and we'll look it up for you.\n"
                    "_(e.g. ORD-20240312-001)_"
                )
                await send_text_message(phone, reply)
                await set_flow_state(phone, {"step": "order_lookup"})
                await save_message(phone, tenant_id, "assistant", reply)
                return

            elif user_text == "flow_support" or "support" in user_text.lower():
                reply = (
                    "💬 *Support*\n\n"
                    "Tell me what you need help with and I'll assist you, "
                    "or I can connect you with our team."
                )
                await send_text_message(phone, reply)
                await set_flow_state(phone, {"step": "support"})
                await save_message(phone, tenant_id, "assistant", reply)
                return

            else:
                # Unexpected input at menu — re-show menu
                await clear_flow_state(phone)
                await process_and_reply(phone, "hi", tenant_id, wa_message_id, customer_name)
                return

        # ══════════════════════════════════════════════════════════
        # STEP: browsing — user selected a product from the list
        # ══════════════════════════════════════════════════════════
        if step == "browsing":
            if user_text.startswith("[PRODUCT_SELECTED:"):
                _, product_id, product_name = user_text.split(":", 2)
                product_name = product_name.rstrip("]")

                # Load product details
                product = await get_product_by_id(product_id)
                if not product:
                    await send_text_message(phone, "Sorry, that product is no longer available.")
                    await clear_flow_state(phone)
                    return

                details = _format_product_details(product)
                await send_button_message(
                    phone=phone,
                    body_text=details,
                    buttons=[
                        {"id": "flow_add_to_order", "title": "✅ Order This"},
                        {"id": "flow_back",         "title": "◀️ Back to List"},
                        {"id": "flow_main_menu",    "title": "🏠 Main Menu"},
                    ],
                )
                await set_flow_state(phone, {
                    "step": "product_detail",
                    "product_id": product_id,
                    "product_name": product_name,
                })
                await save_message(phone, tenant_id, "assistant", f"[Showed product detail: {product_name}]")
                return
            else:
                # They typed instead of selecting — re-show list
                await _send_product_list(phone, tenant_id, customer_name)
                return

        # ══════════════════════════════════════════════════════════
        # STEP: product_detail — customer chose to order or go back
        # ══════════════════════════════════════════════════════════
        if step == "product_detail":
            product_id   = flow.get("product_id")
            product_name = flow.get("product_name")

            if user_text in ("flow_back", "◀️ Back to List"):
                await _send_product_list(phone, tenant_id, customer_name)
                await set_flow_state(phone, {"step": "browsing"})
                return

            elif user_text in ("flow_main_menu", "🏠 Main Menu"):
                await clear_flow_state(phone)
                await process_and_reply(phone, "hi", tenant_id, wa_message_id, customer_name)
                return

            elif user_text in ("flow_add_to_order", "✅ Order This"):
                product = await get_product_by_id(product_id)
                reply = (
                    f"Great choice! 🎉 You selected *{product_name}*.\n\n"
                    f"Please enter the *quantity* you'd like to order:"
                )
                await send_text_message(phone, reply)
                await set_flow_state(phone, {
                    "step": "collect_quantity",
                    "product_id": product_id,
                    "product_name": product_name,
                    "price": product.price,
                    "currency": product.currency,
                })
                await save_message(phone, tenant_id, "assistant", reply)
                return

        # ══════════════════════════════════════════════════════════
        # STEP: collect_quantity
        # ══════════════════════════════════════════════════════════
        if step == "collect_quantity":
            if not user_text.strip().isdigit() or int(user_text.strip()) < 1:
                await send_text_message(phone, "Please enter a valid quantity (e.g. 1, 2, 3):")
                return

            qty = int(user_text.strip())
            await set_flow_state(phone, {**flow, "step": "collect_size", "quantity": qty})
            reply = "What *size* do you need? (e.g. 40, 42, 44)"
            await send_text_message(phone, reply)
            await save_message(phone, tenant_id, "assistant", reply)
            return

        # ══════════════════════════════════════════════════════════
        # STEP: collect_size
        # ══════════════════════════════════════════════════════════
        if step == "collect_size":
            size = user_text.strip()
            await set_flow_state(phone, {**flow, "step": "collect_address", "size": size})
            reply = "📍 What is your *delivery address*?"
            await send_text_message(phone, reply)
            await save_message(phone, tenant_id, "assistant", reply)
            return

        # ══════════════════════════════════════════════════════════
        # STEP: collect_address
        # ══════════════════════════════════════════════════════════
        if step == "collect_address":
            address = user_text.strip()
            await set_flow_state(phone, {**flow, "step": "confirm_order", "address": address})

            # Show order summary for confirmation
            total = flow.get("price", 0) * flow.get("quantity", 1)
            summary = (
                f"📋 *Order Summary*\n\n"
                f"Product : {flow['product_name']}\n"
                f"Size    : {flow.get('size', 'N/A')}\n"
                f"Qty     : {flow.get('quantity', 1)}\n"
                f"Address : {address}\n"
                f"Total   : {flow.get('currency', 'LKR')} {total:,.0f}\n\n"
                f"Delivery in 2-3 business days. 🚚"
            )
            await send_button_message(
                phone=phone,
                body_text=summary,
                buttons=[
                    {"id": "flow_confirm", "title": "✅ Confirm Order"},
                    {"id": "flow_cancel",  "title": "❌ Cancel"},
                ],
            )
            await save_message(phone, tenant_id, "assistant", summary)
            return

        # ══════════════════════════════════════════════════════════
        # STEP: confirm_order — final confirmation
        # ══════════════════════════════════════════════════════════
        if step == "confirm_order":
            if user_text in ("flow_confirm", "✅ Confirm Order"):
                order_id = await create_order(phone, tenant_id, flow)  # see step 3 below
                reply = (
                    f"🎉 *Order Placed Successfully!*\n\n"
                    f"Your order ID is *{order_id}*.\n"
                    f"We'll contact you shortly to confirm delivery.\n\n"
                    f"Thank you for shopping with us! 🙏"
                )
                await send_text_message(phone, reply)
                await save_message(phone, tenant_id, "assistant", reply)
                await clear_flow_state(phone)
                return

            elif user_text in ("flow_cancel", "❌ Cancel"):
                reply = "Order cancelled. No problem! Type *hi* to start again. 😊"
                await send_text_message(phone, reply)
                await save_message(phone, tenant_id, "assistant", reply)
                await clear_flow_state(phone)
                return

        # ══════════════════════════════════════════════════════════
        # STEP: support — pass to AI
        # ══════════════════════════════════════════════════════════
        if step == "support":
            reply_text = await generate_ai_reply(user_text, phone)
            await save_message(phone, tenant_id, "assistant", reply_text)
            within_window = await is_within_24h_window(phone)
            if within_window:
                success = await send_text_message(phone, reply_text)
                if not success:
                    await send_template_message(phone)
            else:
                await send_template_message(phone)
            return

        # ══════════════════════════════════════════════════════════
        # Fallback — treat as new conversation
        # ══════════════════════════════════════════════════════════
        await clear_flow_state(phone)
        await process_and_reply(phone, "hi", tenant_id, wa_message_id, customer_name)

    except Exception as e:
        logger.exception("process_and_reply error for %s: %s", phone, e)

# async def process_and_reply(phone: str, user_text: str, tenant_id: str, wa_message_id: str, customer_name: str = None):
#     try:
#         from src.services.keyword_triggers import check_keyword_triggers
#         from src.models.tenant import Tenant
#         import uuid

#         async with AsyncSessionLocal() as db:
#             tenant = await db.get(Tenant, tenant_id)

#         if not tenant:
#             logger.error("Tenant %s not found", tenant_id)
#             return

#         await save_message(phone, tenant_id, "user", user_text, wa_message_id=wa_message_id)

#         # ── Keyword triggers first ──────────────────────────────────
#         trigger_result = check_keyword_triggers(user_text)
#         if trigger_result:
#             trigger_reply, action = trigger_result
#             if action == "clear_history":
#                 await SessionService.clear(phone)
#             elif action == "escalate":
#                 await set_human_takeover(phone, tenant_id, active=True)
#             await save_message(phone, tenant_id, "assistant", trigger_reply)
#             await send_text_message(phone, trigger_reply)
#             return

#         # ── Detect if user wants to browse products ─────────────────
#         PRODUCT_TRIGGERS = ["product", "products", "items", "catalogue", "catalog",
#                             "what do you have", "show me", "buy", "stock", "available",
#                             "list", "browse", "shop", "shoes", "sneakers"]
        
#         wants_products = any(kw in user_text.lower() for kw in PRODUCT_TRIGGERS)

#         if wants_products:
#             products = await get_products_for_tenant(tenant_id)

#             if not products:
#                 reply = "Sorry, we don't have any products available right now. Please check back soon!"
#                 await save_message(phone, tenant_id, "assistant", reply)
#                 await send_text_message(phone, reply)
#                 return

#             sections = build_product_sections(products)
#             greeting = f"Hi {customer_name}! Here's " if customer_name else "Here's "
            
#             await send_list_message(
#                 phone=phone,
#                 header="Our Products",
#                 body=f"{greeting}what we currently have in stock. Tap below to browse and select an item:",
#                 button_label="View Products",
#                 sections=sections,
#             )
#             # Save a note of what we sent
#             await save_message(phone, tenant_id, "assistant", "[Sent product list to customer]")
#             return

#     except Exception as e:
#         logger.exception("process_and_reply error for %s: %s", phone, e)