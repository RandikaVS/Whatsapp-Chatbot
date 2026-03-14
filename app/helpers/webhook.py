# app/helpers/webhook.py
from app.config import settings
from app.services.session import SessionService
import logging
import httpx

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


def extract_user_text(msg: dict) -> tuple[str, bool]:
    """
    Extracts a human-readable representation of any message type.
    
    Returns a tuple of (text_to_send_to_ai, should_reply).
    The second value is False for things like reactions — you want to
    log them but not trigger an AI response, because sending a reply
    to a reaction looks very strange to the user.
    """
    msg_type = msg.get("type", "text")

    if msg_type == "text":
        return msg["text"]["body"], True

    elif msg_type == "image":
        # Caption is optional — the user may just send a photo with no text
        caption = msg.get("image", {}).get("caption", "")
        text = f"[Customer sent an image{': ' + caption if caption else ''}]"
        return text, True

    elif msg_type == "audio":
        # In future you can transcribe this with Whisper — for now acknowledge it
        return "[Customer sent a voice message. Please reply as text.]", True

    elif msg_type == "video":
        caption = msg.get("video", {}).get("caption", "")
        text = f"[Customer sent a video{': ' + caption if caption else ''}]"
        return text, True

    elif msg_type == "document":
        filename = msg.get("document", {}).get("filename", "a file")
        return f"[Customer sent a document: {filename}]", True

    elif msg_type == "sticker":
        # Stickers are usually a casual acknowledgement — a short friendly reply is fine
        return "[Customer sent a sticker]", True

    elif msg_type == "location":
        # Very useful for businesses like delivery services or restaurants
        loc = msg.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        name = loc.get("name", "")
        address = loc.get("address", "")
        text = f"[Customer shared their location: {name} {address} (lat: {lat}, lng: {lng})]"
        return text, True

    elif msg_type == "contacts":
        # Someone forwarded a contact card
        contacts = msg.get("contacts", [])
        names = [c.get("name", {}).get("formatted_name", "Unknown") for c in contacts]
        return f"[Customer shared contact(s): {', '.join(names)}]", True

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            # Customer tapped one of your quick-reply buttons
            return interactive["button_reply"]["title"], True
        elif interactive.get("type") == "list_reply":
            # Customer selected from your list menu
            return interactive["list_reply"]["title"], True
        elif interactive.get("type") == "nfm_reply":
            # Native flow message reply (WhatsApp Forms)
            return "[Customer submitted a form response]", True
        return "[Customer sent an interactive message]", True

    elif msg_type == "order":
        # Customer placed an order from your WhatsApp catalog
        order = msg.get("order", {})
        items = order.get("product_items", [])
        item_list = ", ".join([f"{i.get('product_retailer_id')} x{i.get('quantity')}" for i in items])
        return f"[Customer placed an order: {item_list}]", True

    elif msg_type == "reaction":
        # Someone reacted with an emoji — DO NOT reply to this
        # It would be very weird to get "Thanks for your message!" after sending a 👍
        emoji = msg.get("reaction", {}).get("emoji", "")
        return f"[Customer reacted with {emoji}]", False  # <-- should_reply = False

    elif msg_type == "unsupported":
        return "[Customer sent a message type that is not supported yet]", True

    else:
        return f"[Customer sent a {msg_type} message]", True