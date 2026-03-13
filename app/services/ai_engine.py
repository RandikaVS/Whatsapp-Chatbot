# app/services/ai_engine.py
from google import genai
from google.genai import types
from app.services.session import SessionService
from app.services.catalog import build_system_prompt_with_catalog
from app.models import Tenant
from app.database import get_db_sync   # sync version for background tasks
import logging

logger = logging.getLogger(__name__)


async def generate_ai_reply(
    user_text: str,
    phone: str,
    tenant: Tenant,
    db
) -> str:
    """
    Full AI reply generation:
    1. Loads tenant's system prompt + live product catalog
    2. Loads conversation history from Redis
    3. Calls Gemini with full context
    4. Returns reply and saves history
    """
    from app.config import settings

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # Load the system prompt enriched with the tenant's live product catalog
    system_prompt = await build_system_prompt_with_catalog(tenant, db)

    # Load this customer's conversation history from Redis
    history = await SessionService.get_history(phone)

    # Build contents in Gemini format
    contents = []

    for h in history[-10:]:  # last 10 turns = enough context, saves tokens
        gemini_role = "model" if h["role"] == "assistant" else "user"
        contents.append(
            types.Content(
                role=gemini_role,
                parts=[types.Part(text=h["content"])]
            )
        )

    # Add the current message
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_text)]
        )
    )

    try:
        response = client.models.generate_content(
            model=tenant.ai_model or "gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=500,
                temperature=0.7,
            ),
        )

        reply = response.text.strip()

        # Save both sides of the conversation to Redis
        await SessionService.append(phone, "user", user_text)
        await SessionService.append(phone, "assistant", reply)

        return reply

    except Exception as e:
        logger.exception("AI generation failed for tenant %s: %s", tenant.id, e)
        return "Sorry, I'm having trouble right now. Please try again in a moment."