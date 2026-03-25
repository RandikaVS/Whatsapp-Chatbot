import redis
import json
from src.config import settings
import time


redis_client = redis.Redis.from_url(settings.REDIS_URL)

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



async def is_duplicate(msg_id: str) -> bool:
    """
    Returns True if we've already processed this message.
    
    We store msg_id in Redis with a 24-hour TTL. WhatsApp message IDs
    are unique globally — they will never repeat — so if we've seen it,
    it's a duplicate delivery from Meta's infrastructure.
    """
    key = f"processed_msg:{msg_id}"
    
    # SET key value NX = only set if not exists, returns True if newly set
    # This is an atomic operation — no race condition even under high load
    was_set = await redis_client.set(key, "1", nx=True, ex=86400)  # 24h TTL
    
    # was_set is True if we just set it (first time seen = not duplicate)
    # was_set is None if key already existed (duplicate!)
    return was_set is None
