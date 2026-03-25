# app/services/flow.py
import json
from app.services.session import redis_client

FLOW_TTL = 60 * 30  # 30 minutes

async def get_flow_state(phone: str) -> dict:
    raw = await redis_client.get(f"flow:{phone}")
    return json.loads(raw) if raw else {}

async def set_flow_state(phone: str, state: dict):
    await redis_client.setex(f"flow:{phone}", FLOW_TTL, json.dumps(state))

async def clear_flow_state(phone: str):
    await redis_client.delete(f"flow:{phone}")