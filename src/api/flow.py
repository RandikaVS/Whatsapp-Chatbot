# src/api/flow.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
import json
import logging

from src.database import get_db
from src.models.tenant import Tenant
from src.helpers.tenant_dependency import get_current_tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/flow", tags=["flow"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FlowButton(BaseModel):
    id:    str
    title: str


class FlowStep(BaseModel):
    step_key:     str
    step_index:   int
    display_name: str
    is_enabled:   bool   = True
    message:      str    = ""
    buttons:      List[FlowButton] = []
    description:  str    = ""


class FlowConfigRequest(BaseModel):
    steps: List[FlowStep]


class FlowConfigResponse(BaseModel):
    steps: List[FlowStep]


# ── Default flow (fallback if tenant hasn't customized) ───────────────────────

DEFAULT_STEPS = [
    {
        "step_index": 0, "step_key": "idle", "display_name": "Idle / Entry",
        "is_enabled": True,
        "description": "Triggered when customer says hi/hello/start/help",
        "message": "Hi {{customer_name}}! 👋 Welcome to *{{business_name}}*!\n\nHow can I help you today?",
        "buttons": [
            {"id": "flow_browse",  "title": "🛍️ Browse Products"},
            {"id": "flow_order",   "title": "📦 My Orders"},
            {"id": "flow_support", "title": "💬 Support"},
        ],
    },
    {
        "step_index": 1, "step_key": "main_menu", "display_name": "Main Menu",
        "is_enabled": True,
        "description": "Routes customer to Browse, Orders, or Support",
        "message": "Please choose an option below:",
        "buttons": [
            {"id": "flow_browse",  "title": "🛍️ Browse Products"},
            {"id": "flow_order",   "title": "📦 My Orders"},
            {"id": "flow_support", "title": "💬 Support"},
        ],
    },
    {
        "step_index": 2, "step_key": "browsing", "display_name": "Product Browser",
        "is_enabled": True,
        "description": "Shows product list from catalog as WhatsApp list",
        "message": "Here are our available products 👇\n\nTap a product to see details and order.",
        "buttons": [],
    },
    {
        "step_index": 3, "step_key": "product_detail", "display_name": "Product Detail",
        "is_enabled": True,
        "description": "Shows product details with Order / Back buttons",
        "message": "{{product_details}}",
        "buttons": [
            {"id": "flow_add_to_order", "title": "✅ Order This"},
            {"id": "flow_back",         "title": "◀️ Back to List"},
            {"id": "flow_main_menu",    "title": "🏠 Main Menu"},
        ],
    },
    {
        "step_index": 4, "step_key": "collect_quantity", "display_name": "Collect Quantity",
        "is_enabled": True,
        "description": "Asks how many units the customer wants",
        "message": "Great choice! 🎉 You selected *{{product_name}}*.\n\nPlease enter the *quantity* you'd like to order:",
        "buttons": [],
    },
    {
        "step_index": 5, "step_key": "collect_size", "display_name": "Collect Size",
        "is_enabled": True,
        "description": "Asks customer for their size",
        "message": "What *size* do you need? (e.g. 40, 42, 44)",
        "buttons": [],
    },
    {
        "step_index": 6, "step_key": "collect_address", "display_name": "Collect Address",
        "is_enabled": True,
        "description": "Asks for delivery address",
        "message": "📍 What is your *delivery address*?",
        "buttons": [],
    },
    {
        "step_index": 7, "step_key": "confirm_order", "display_name": "Order Confirmation",
        "is_enabled": True,
        "description": "Shows order summary and asks for confirmation",
        "message": (
            "📋 *Order Summary*\n\n"
            "Product : {{product_name}}\n"
            "Size    : {{size}}\n"
            "Qty     : {{quantity}}\n"
            "Address : {{address}}\n"
            "Total   : {{currency}} {{total}}\n\n"
            "Delivery in 2-3 business days. 🚚"
        ),
        "buttons": [
            {"id": "flow_confirm", "title": "✅ Confirm Order"},
            {"id": "flow_cancel",  "title": "❌ Cancel"},
        ],
    },
    {
        "step_index": 8, "step_key": "support", "display_name": "AI Support Chat",
        "is_enabled": True,
        "description": "Hands off to AI using system prompt from My Agent settings",
        "message": "💬 *Support*\n\nTell me what you need help with and I'll assist you right away.",
        "buttons": [],
    },
]

async def get_current_tenant_test(db):

    result = await db.execute(
        select(Tenant).where(
            Tenant.email == 'test@abcshoes.lk',
        )
    )
    tenant = result.scalar_one_or_none()
    return tenant

# ── GET /api/flow/config ──────────────────────────────────────────────────────

@router.get("/config", response_model=FlowConfigResponse)
async def get_flow_config(
    db:AsyncSession = Depends(get_db)
):
    tenant = await get_current_tenant_test(db)

    if tenant:
        if tenant.flow_config:
            try:
                saved = json.loads(tenant.flow_config) if isinstance(tenant.flow_config, str) \
                        else tenant.flow_config
                steps = saved.get("steps", DEFAULT_STEPS)
                return FlowConfigResponse(steps=[FlowStep(**s) for s in steps])
            except Exception:
                pass  # fall through to defaults if JSON is malformed

        return FlowConfigResponse(steps=[FlowStep(**s) for s in DEFAULT_STEPS])


# ── PUT /api/flow/config ──────────────────────────────────────────────────────

@router.put("/config", response_model=FlowConfigResponse)
async def update_flow_config(
    data:   FlowConfigRequest,
    db:     AsyncSession = Depends(get_db),
):
    tenant = await get_current_tenant_test(db)

    steps = data.steps

    # Validation
    step_keys = [s.step_key for s in steps]
    if len(step_keys) != len(set(step_keys)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate step keys found. Each step must have a unique key."
        )

    for step in steps:
        if len(step.buttons) > 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Step '{step.display_name}' has more than 3 buttons. WhatsApp only allows max 3 quick reply buttons."
            )
        for btn in step.buttons:
            if len(btn.title) > 20:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Button '{btn.title}' in step '{step.display_name}' exceeds 20 characters."
                )

    # Save as JSON in the tenant's flow_config column
    config_json = {"steps": [s.model_dump() for s in steps]}

    tenant_in_session = await db.merge(tenant)
    tenant_in_session.flow_config = config_json
    await db.commit()

    logger.info("Flow config updated for tenant %s (%s)", tenant.id, tenant.business_name)

    return FlowConfigResponse(steps=steps)


# ── GET /api/flow/config/step/{step_key} ──────────────────────────────────────

@router.get("/config/step/{step_key}")
async def get_flow_step(
    step_key: str,
    tenant:   Tenant       = Depends(get_current_tenant),
    db:       AsyncSession = Depends(get_db),
):
    """
    Returns a single step's config by key.
    Used by the webhook at runtime to get the current message/buttons
    for a given step — so the bot reflects the tenant's customizations.
    """
    if tenant.flow_config:
        try:
            saved = json.loads(tenant.flow_config) if isinstance(tenant.flow_config, str) \
                    else tenant.flow_config
            steps = saved.get("steps", DEFAULT_STEPS)
        except Exception:
            steps = DEFAULT_STEPS
    else:
        steps = DEFAULT_STEPS

    for step in steps:
        key = step.get("step_key") if isinstance(step, dict) else step.step_key
        if key == step_key:
            return step

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Step '{step_key}' not found in flow config"
    )