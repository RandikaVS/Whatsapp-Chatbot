# src/services/flow.py

import json
from src.services.session import get_redis
import redis.asyncio as redis
from fastapi import Depends

FLOW_TTL = 60 * 30


async def get_flow_state(phone: str, redis_client: redis.Redis) -> dict:

    if redis_client is None:
        raise Exception("Redis not initialized")
    
    key = f"flow:{phone}"

    raw = await redis_client.get(key)

    return json.loads(raw) if raw else {}


async def set_flow_state(phone: str, state: dict, redis_client: redis.Redis):

    await redis_client.setex(
        f"flow:{phone}",
        FLOW_TTL,
        json.dumps(state)
    )


async def clear_flow_state(phone: str, redis_client: redis.Redis):

    await redis_client.delete(f"flow:{phone}")