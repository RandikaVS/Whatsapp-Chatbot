# app/api/agent.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.models.Tenant import Tenant
from app.models.Conversation import Conversation
from app.models.Message import Message
from app.schemas.agent import (
    AgentConfigResponse, AgentConfigUpdate,
    AgentTestRequest, AgentTestResponse,
    AgentStatsResponse,
)
# The key change: import get_current_tenant, not get_current_admin
from app.helpers.tenant_dependency import get_current_tenant
from ..services.ai_engine import generate_ai_reply

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

async def get_current_tenant_test(db):

    result = await db.execute(
        select(Tenant).where(
            Tenant.email == 'test@abcshoes.lk',
        )
    )
    tenant = result.scalar_one_or_none()
    return tenant


# ── GET /api/agent/config ─────────────────────────────────────────────────────

@router.get("/config", response_model=AgentConfigResponse)
async def get_agent_config(
    # 'tenant' IS the logged-in client — no lookup needed
    db: AsyncSession = Depends(get_db),

):
    """
    Returns the bot configuration for the currently logged-in client.
    The tenant object already contains everything we need — we just
    map its fields to the response schema.
    Note: no 'db' dependency needed here because we're not querying
    anything extra — the tenant object came fully loaded from get_current_tenant.
    """
    tenant = await get_current_tenant_test(db)

    return AgentConfigResponse(
        business_name         = tenant.business_name,
        is_bot_active         = tenant.is_bot_active,
        system_prompt         = tenant.system_prompt         or "",
        welcome_message       = tenant.welcome_message       or "",
        ai_model              = tenant.ai_model              or "gemini-2.0-flash",
        language              = tenant.language              or "auto",
        temperature           = float(tenant.temperature     or 0.7),
        max_tokens            = tenant.max_tokens            or 400,
        reply_delay_seconds   = tenant.reply_delay_seconds   or 0,
        plan                  = tenant.plan                  or "starter",
        monthly_message_limit = tenant.monthly_message_limit or 1000,
        messages_used         = tenant.messages_used         or 0,
        wa_connected          = bool(tenant.wa_phone_number_id and tenant.wa_access_token),
    )


# ── PUT /api/agent/config ─────────────────────────────────────────────────────

@router.put("/config", response_model=AgentConfigResponse)
async def update_agent_config(
    data: AgentConfigUpdate,
    tenant: Tenant       = Depends(get_current_tenant_test),
    db:     AsyncSession = Depends(get_db),
):
    """
    Updates only the fields the client sent — partial update pattern.
    Because 'tenant' is a SQLAlchemy model instance already loaded in
    get_current_tenant's session, we need to merge it into this route's
    session before modifying it. The db.merge() call does exactly that —
    it takes an object from one session and makes it manageable in another.
    """
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update."
        )

    # Merge the tenant into this request's database session so
    # SQLAlchemy can track changes and commit them properly
    tenant_in_session = await db.merge(tenant)

    for field, value in updates.items():
        setattr(tenant_in_session, field, value)

    await db.commit()
    await db.refresh(tenant_in_session)

    logger.info("Config updated for tenant %s (%s)", tenant.id, tenant.business_name)

    # Return the refreshed tenant's config
    return AgentConfigResponse(
        business_name         = tenant_in_session.business_name,
        is_bot_active         = tenant_in_session.is_bot_active,
        system_prompt         = tenant_in_session.system_prompt         or "",
        welcome_message       = tenant_in_session.welcome_message       or "",
        ai_model              = tenant_in_session.ai_model              or "gemini-2.0-flash",
        language              = tenant_in_session.language              or "auto",
        temperature           = float(tenant_in_session.temperature     or 0.7),
        max_tokens            = tenant_in_session.max_tokens            or 400,
        reply_delay_seconds   = tenant_in_session.reply_delay_seconds   or 0,
        plan                  = tenant_in_session.plan                  or "starter",
        monthly_message_limit = tenant_in_session.monthly_message_limit or 1000,
        messages_used         = tenant_in_session.messages_used         or 0,
        wa_connected          = bool(
            tenant_in_session.wa_phone_number_id and tenant_in_session.wa_access_token
        ),
    )


# ── POST /api/agent/test ──────────────────────────────────────────────────────

@router.post("/test", response_model=AgentTestResponse)
async def test_agent(
    data:   AgentTestRequest,
    db:     AsyncSession = Depends(get_db), 
):
    
    try:
        tenant = await get_current_tenant_test(db)
        response = await generate_ai_reply(data.message,tenant,db,tenant.wa_phone_number_id)

        return AgentTestResponse(
            reply=response,
            model_used=data.model,
            tokens_used=0
        )

    except Exception as e:
        logger.exception("Test failed for tenant %s: %s", tenant.id, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service error: {str(e)}"
        )


# ── GET /api/agent/stats ──────────────────────────────────────────────────────

@router.get("/stats", response_model=AgentStatsResponse)
async def get_agent_stats(
    # tenant: Tenant       = Depends(get_current_tenant_test),
    db:     AsyncSession = Depends(get_db),
):
    tenant = await get_current_tenant_test(db)

    now         = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    conv_result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.tenant_id  == tenant.id,
            Conversation.started_at >= month_start,
        )
    )

    msg_result = await db.execute(
        select(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == tenant.id,
            Message.role           == "assistant",
            Message.created_at     >= month_start,
        )
    )

    escalation_result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.tenant_id         == tenant.id,
            Conversation.is_human_takeover == True,
            Conversation.started_at        >= month_start,
        )
    )

    return AgentStatsResponse(
        conversations_this_month  = conv_result.scalar()      or 0,
        messages_handled          = msg_result.scalar()       or 0,
        escalations_this_month    = escalation_result.scalar() or 0,
        avg_response_time_seconds = 1.4,
    )