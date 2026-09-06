import secrets

import redis.asyncio

from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.providers.base import SmsProvider
from app.repositories.user_repo import UserRepo


def _get_str(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


class AuthService:
    def __init__(self, user_repo: UserRepo, sms_provider: SmsProvider,
                 redis: redis.asyncio.Redis, settings: Settings):
        self.user_repo = user_repo
        self.sms_provider = sms_provider
        self.redis = redis
        self.settings = settings

    async def send_code(self, phone: str) -> int:
        if await self.redis.exists(f"sms:limit:{phone}"):
            raise RateLimitedError()
        code = f"{secrets.randbelow(10**6):06d}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.setex(f"sms:code:{phone}", self.settings.sms_code_ttl_seconds, code)
            pipe.setex(f"sms:limit:{phone}", self.settings.sms_send_limit_seconds, "1")
            await pipe.execute()
        await self.sms_provider.send_code(phone, code)
        return self.settings.sms_code_ttl_seconds
