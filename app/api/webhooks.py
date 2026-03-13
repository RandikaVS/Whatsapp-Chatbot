# app/api/webhook.py
from fastapi import APIRouter, Request, HTTPException, Query, BackgroundTasks, Depends
import httpx
import logging
from ..config import settings
from ..services.session import SessionService, update_customer_message_timestamp, is_within_24h_window
from ..helpers.webhook import detect_event_type, generate_ai_reply
from ..database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

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
                    _handle_status_update(value)

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

    await update_customer_message_timestamp(phone)

    # Extract text safely based on message type
    if msg_type == "text":
        user_text = msg["text"]["body"]
    elif msg_type == "image":
        user_text = msg.get("image", {}).get("caption", "[Image received]")
    elif msg_type == "audio":
        user_text = "[Voice message received]"
    elif msg_type == "document":
        user_text = "[Document received]"
    elif msg_type == "interactive":
        # Button reply or list reply
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            user_text = interactive["button_reply"]["title"]
        elif interactive.get("type") == "list_reply":
            user_text = interactive["list_reply"]["title"]
        else:
            user_text = "[Interactive message]"
    else:
        user_text = f"[{msg_type} message]"

    logger.info("Incoming | phone=%s | type=%s | text=%s", phone, msg_type, user_text)

    # Mark as read immediately (shows blue ticks to user)
    bg.add_task(mark_as_read, msg_id)

    # Send AI reply in background
    bg.add_task(process_and_reply, phone, user_text)


def _handle_status_update(value: dict):
    status = value["statuses"][0]
    status_type  = status.get("status")        # sent | delivered | read | failed
    recipient    = status.get("recipient_id")
    message_id   = status.get("id")

    if status_type == "failed":
        errors = status.get("errors", [])
        for err in errors:
            code    = err.get("code")
            title   = err.get("title")
            details = err.get("error_data", {}).get("details", "")

            logger.error(
                "Message FAILED | to=%s | msg_id=%s | code=%s | reason=%s | detail=%s",
                recipient, message_id, code, title, details
            )

            # Handle specific error codes
            if code == 131047:
                logger.warning(
                    "24-hour window expired for %s. "
                    "Must use approved template for re-engagement.", recipient
                )
            elif code == 131026:
                logger.warning("Recipient %s does not have WhatsApp.", recipient)
            elif code == 130429:
                logger.warning("Rate limit hit. Slow down sending.")

    else:
        pricing = status.get("pricing", {})
        logger.info(
            "Status: %s | to=%s | msg_id=%s | billable=%s | category=%s",
            status_type, recipient, message_id,
            pricing.get("billable"), pricing.get("category")
        )


async def process_and_reply(phone: str, user_text: str):
    try:
        reply_text = await generate_ai_reply(user_text, phone)

        within_window = await is_within_24h_window(phone)
        
        if within_window:
            # Free text — customer messaged within 24h
            success = await send_text_message(phone, reply_text)
            if not success:
                # Text failed anyway, fall back to template
                await send_template_message(phone)
        else:
            # Outside window — only templates allowed
            # Use hello_world (always approved) or your own approved template
            await send_template_message(phone)

    except Exception as e:
        logger.exception("process_and_reply error for %s: %s", phone, e)


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
    """
    Returns True if sent successfully.
    Returns False if failed (e.g. 131047 window expired).
    """
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
        "Authorization": f"Bearer {settings.CHATBOT_ACCESS_TOKEN}",
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
        "Authorization": f"Bearer {settings.CHATBOT_ACCESS_TOKEN}",
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
