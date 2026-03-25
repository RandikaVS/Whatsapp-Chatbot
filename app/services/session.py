# app/services/session.py
import json
import time
from collections import defaultdict

# ── In-memory stores (process-local, resets on restart) ──────────────────────
_sessions: dict[str, list]  = defaultdict(list)   # phone → message history
_last_msg_ts: dict[str, float] = {}               # phone → last customer msg timestamp
_processed_msgs: set[str] = set()                 # seen message IDs (dedup)


class _NoOpRedis:
    async def get(self, key): return None
    async def set(self, *a, **kw): return True
    async def setex(self, *a, **kw): pass
    async def delete(self, *a, **kw): pass

redis_client = _NoOpRedis()

class SessionService:
    TTL_MESSAGES = 20  # keep last 20 messages per session

    @staticmethod
    async def get_history(phone: str) -> list:
        return list(_sessions[phone])

    @staticmethod
    async def append(phone: str, role: str, content: str):
        _sessions[phone].append({"role": role, "content": content})
        _sessions[phone] = _sessions[phone][-SessionService.TTL_MESSAGES:]

    @staticmethod
    async def clear(phone: str):
        _sessions[phone] = []


async def is_within_24h_window(phone: str) -> bool:
    ts = _last_msg_ts.get(phone)
    if not ts:
        return False
    return (time.time() - ts) < 86400


async def update_customer_message_timestamp(phone: str):
    _last_msg_ts[phone] = time.time()


async def is_duplicate(msg_id: str) -> bool:
    if msg_id in _processed_msgs:
        return True
    _processed_msgs.add(msg_id)
    return False










# import redis.asyncio as redis
# import json
# from app.config import settings
# import time

# redis_client = redis.from_url(settings.REDIS_URL)



# class SessionService:

#     TTL = 60 * 60 * 24  # 24 hours session expiry

#     @staticmethod
#     async def get_history(phone: str) -> list:
#         key = f"session:{phone}"
#         data = await redis_client.get(key)
#         return json.loads(data) if data else []

#     @staticmethod
#     async def append(phone: str, role: str, content: str):
#         key = f"session:{phone}"
#         history = await SessionService.get_history(phone)
#         history.append({"role": role, "content": content})
#         history = history[-20:]  # keep last 20 messages only
#         await redis_client.setex(key, SessionService.TTL, json.dumps(history))

#     @staticmethod
#     async def clear(phone: str):
#         key = f"session:{phone}"
#         await redis_client.delete(key)

    
# async def is_within_24h_window(phone: str) -> bool:
    
#     key = f"last_customer_msg:{phone}"
#     ts = await redis_client.get(key)
#     if not ts:
#         return False
#     return (time.time() - float(ts)) < 86400  # 86400 seconds = 24 hours

# async def update_customer_message_timestamp(phone: str):
    
#     key = f"last_customer_msg:{phone}"
#     await redis_client.setex(key, 86400, str(time.time()))



# async def is_duplicate(msg_id: str) -> bool:
#     """
#     Returns True if we've already processed this message.
    
#     We store msg_id in Redis with a 24-hour TTL. WhatsApp message IDs
#     are unique globally — they will never repeat — so if we've seen it,
#     it's a duplicate delivery from Meta's infrastructure.
#     """
#     key = f"processed_msg:{msg_id}"
    
#     # SET key value NX = only set if not exists, returns True if newly set
#     # This is an atomic operation — no race condition even under high load
#     was_set = await redis_client.set(key, "1", nx=True, ex=86400)  # 24h TTL
    
#     # was_set is True if we just set it (first time seen = not duplicate)
#     # was_set is None if key already existed (duplicate!)
#     return was_set is None
