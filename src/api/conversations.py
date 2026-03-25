# src/api/agent.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.helpers.auth_dependency import get_current_admin
from src.services.ai_engine import generate_ai_reply_with_config

router = APIRouter(prefix="/api/agent", tags=["agent"])

@router.get("/api/conversations")
async def list_conversations(tenant_id: str, admin=Depends(get_current_admin), db=Depends(get_db)):
    """
    Returns conversations with pre-computed AI insights.
    For a production system you would compute insights async in the background
    when each conversation ends, then cache them — not compute on every request.
    """
    result = await db.execute(
        select(Conversation, Message)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_message_at.desc())
    )
    # Build the insight object using your Gemini call
    # satisfaction_score = await compute_satisfaction(messages)
    # sentiment = await classify_sentiment(messages)
    return conversations_with_insights


@router.post("/api/conversations/{conversation_id}/takeover")
async def set_takeover(conversation_id: str, active: bool, admin=Depends(get_current_admin), db=Depends(get_db)):
    """The Take Over / Resume Bot button calls this."""
    await set_human_takeover(conversation_id=conversation_id, active=active, db=db)
    return {"status": "updated"}