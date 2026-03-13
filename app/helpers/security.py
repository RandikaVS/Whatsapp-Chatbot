# app/helpers/security.py
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from app.config import settings

# CryptContext manages which hashing algorithm to use.
# bcrypt is the gold standard for password hashing — it is intentionally
# slow to compute, which makes brute-force attacks impractical.
# The "deprecated=auto" means if you ever upgrade to a newer algorithm,
# old passwords are automatically flagged for re-hashing on next login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Turns "mypassword123" into something like:
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCO..."
    
    You call this when creating or updating an admin account.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Returns True if the plain password matches the stored hash.
    
    Internally, bcrypt extracts the salt from the hash and re-hashes
    the plain password, then compares. You never need to manage
    the salt manually — passlib handles it.
    """
    return pwd_context.verify(plain_password, hashed_password)


def generate_access_token(subject: str) -> str:
    """
    Creates a signed JWT token that encodes the admin's ID.
    
    A JWT has three parts: header.payload.signature
    - The payload contains: who this is for (sub), when it expires (exp)
    - The signature is created using your JWT_SECRET_KEY — only your server
      can create or verify valid tokens
    - The token is NOT encrypted — anyone can read the payload,
      but they cannot forge a new token without the JWT_SECRET_KEY
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,        # subject — the admin's UUID as a string
        "exp": expire,         # expiry — JWT library enforces this automatically
        "type": "access",      # custom claim so we can distinguish access vs refresh
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def generate_refresh_token(subject: str) -> str:
    """
    A refresh token lives longer than an access token (e.g. 7 days vs 30 minutes).
    When the access token expires, the frontend sends the refresh token to get
    a new access token — without asking the user to log in again.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Verifies the token signature and returns the payload.
    Raises JWTError if the token is invalid, expired, or tampered with.
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")