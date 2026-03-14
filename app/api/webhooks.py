# app/api/webhook.py
from fastapi import APIRouter, Request, HTTPException, Query, BackgroundTasks, Depends
import httpx
import logging
from ..config import settings
from ..services.session import SessionService, update_customer_message_timestamp, is_within_24h_window, is_duplicate
from ..helpers.webhook import detect_event_type, generate_ai_reply, handle_status_update,send_template_message,send_text_message,send_button_message,mark_as_read,extract_user_text
from ..database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from ..services.conversation import is_human_takeover_active, set_human_takeover
from ..services.message_store import save_message
from app.database import AsyncSessionLocal

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
    from app.services.tenant import get_tenant_by_phone_number_id
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
    """
    The complete production-ready message processing pipeline.
    
    Order matters here:
    1. Check for human takeover (fastest exit)
    2. Save the incoming message to DB permanently
    3. Check keyword triggers (skip AI if matched)
    4. Generate AI reply
    5. Save AI reply to DB
    6. Send to WhatsApp (with 24h window awareness)
    """

    try:
        from app.services.keyword_triggers import check_keyword_triggers
        from app.models.Tenant import Tenant
        import uuid

        # ── Load the tenant's full config ──────────────────────────
        async with AsyncSessionLocal() as db:
            tenant = await db.get(Tenant, tenant_id)

        if not tenant:
            logger.error("Tenant %s disappeared between message receipt and processing", tenant_id)
            return
        
        # Step 1 — Bot is silent during human takeover
        if await is_human_takeover_active(phone, tenant_id):
            logger.info("Human takeover active for %s — bot silent", phone)
            return

        # Step 2 — Permanently save the customer's message
        await save_message(phone, tenant_id, "user", user_text,
                           wa_message_id=wa_message_id)

        # Step 3 — Check keyword triggers before calling the AI
        trigger_result = check_keyword_triggers(user_text)
        if trigger_result:
            trigger_reply, action = trigger_result
            if action == "clear_history":
                await SessionService.clear(phone)
            elif action == "escalate":
                await set_human_takeover(phone, tenant_id, active=True)
            await save_message(phone, tenant_id, "assistant", trigger_reply)
            await send_text_message(phone, trigger_reply)
            return

        # Step 4 — Generate AI reply
        reply_text = await generate_ai_reply(user_text, phone)

        # Step 5 — Save AI reply to DB
        await save_message(phone, tenant_id, "assistant", reply_text)

        # Step 6 — Send with 24h window awareness
        within_window = await is_within_24h_window(phone)
        if within_window:
            success = await send_text_message(phone, reply_text)
            if not success:
                await send_template_message(phone)
        else:
            await send_template_message(phone)

    except Exception as e:
        logger.exception("process_and_reply error for %s: %s", phone, e)

