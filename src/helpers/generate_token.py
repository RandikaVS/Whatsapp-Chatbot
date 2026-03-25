
from datetime import datetime, timedelta, UTC

from jose import jwt
from src.config import settings


def generate_token(admin_id: str):
    payload = {
        "admin_id": admin_id,
        "exp": datetime.now(UTC) + timedelta(hours=24)  # token expires in 24 hours
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    return token