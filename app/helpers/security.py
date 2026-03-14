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


# app/helpers/security.py — update these two functions

def generate_access_token(subject: str, token_type: str = "access") -> str:
    """
    token_type can be "access" (for admins) or "tenant" (for business clients).
    Embedding the type in the token means the dependency can reject the wrong
    type of token without even hitting the database.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub":  subject,
        "exp":  expire,
        "type": token_type,   # "access" for admins, "tenant" for clients
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def generate_refresh_token(subject: str, token_type: str = "refresh") -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub":  subject,
        "exp":  expire,
        "type": token_type,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    """
    Verifies the token signature and returns the payload.
    Raises JWTError if the token is invalid, expired, or tampered with.
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")