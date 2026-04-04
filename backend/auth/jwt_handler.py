import uuid
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from ..config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),
        "type": REFRESH_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None
