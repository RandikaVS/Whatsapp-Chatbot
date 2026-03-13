import redis.asyncio as redis
import json
from app.config import settings
import time

redis_client = redis.from_url(settings.REDIS_URL)

class SessionService:

    TTL = 60 * 60 * 24  # 24 hours session expiry

    @staticmethod
    async def get_history(phone: str) -> list:
        key = f"session:{phone}"
        data = await redis_client.get(key)
        return json.loads(data) if data else []

    @staticmethod
    async def append(phone: str, role: str, content: str):
        key = f"session:{phone}"
        history = await SessionService.get_history(phone)
        history.append({"role": role, "content": content})
        history = history[-20:]  # keep last 20 messages only
        await redis_client.setex(key, SessionService.TTL, json.dumps(history))

    @staticmethod
    async def clear(phone: str):
        key = f"session:{phone}"
        await redis_client.delete(key)

    
async def is_within_24h_window(phone: str) -> bool:
    
    key = f"last_customer_msg:{phone}"
    ts = await redis_client.get(key)
    if not ts:
        return False
    return (time.time() - float(ts)) < 86400  # 86400 seconds = 24 hours

async def update_customer_message_timestamp(phone: str):
    
    key = f"last_customer_msg:{phone}"
    await redis_client.setex(key, 86400, str(time.time()))