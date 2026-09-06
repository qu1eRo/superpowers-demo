import secrets
from datetime import datetime, timedelta, timezone

import jwt


def create_access_token(user_id: int, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "exp": now + timedelta(minutes=ttl_minutes), "iat": now}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> int:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    return int(payload["sub"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)
