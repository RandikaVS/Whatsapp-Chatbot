# app/helpers/webhook.py
from app.config import settings
from app.services.session import SessionService


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