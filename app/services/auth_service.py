import secrets

import redis.asyncio

from app.core.config import Settings
from app.core.errors import InvalidCodeError, InvalidTokenError, RateLimitedError, TooManyAttemptsError
from app.core.security import create_access_token, generate_refresh_token
from app.providers.base import SmsProvider
from app.repositories.user_repo import UserRepo
from app.schemas.auth import TokenPair, VerifyResponse


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

    async def verify(self, phone: str, code: str) -> VerifyResponse:
        fail_key = f"sms:fail:{phone}"
        fails = int(_get_str(await self.redis.get(fail_key)) or 0)
        if fails >= self.settings.sms_max_fail_count:
            raise TooManyAttemptsError()

        stored = _get_str(await self.redis.get(f"sms:code:{phone}"))
        if stored is None or stored != code:
            pipe = self.redis.pipeline()
            pipe.incr(fail_key)
            pipe.expire(fail_key, self.settings.sms_code_ttl_seconds)
            await pipe.execute()
            raise InvalidCodeError()

        await self.redis.delete(f"sms:code:{phone}", fail_key)

        user = await self.user_repo.get_by_phone(phone)
        is_new = user is None
        if is_new:
            user = await self.user_repo.create(phone)

        access, refresh = await self._issue_tokens(user.id)
        return VerifyResponse(access_token=access, refresh_token=refresh,
                              user_id=user.id, is_new=is_new)

    async def refresh(self, refresh_token: str) -> TokenPair:
        key = f"refresh:{refresh_token}"
        user_id = _get_str(await self.redis.get(key))
        if user_id is None:
            raise InvalidTokenError()
        await self.redis.delete(key)
        access, new_refresh = await self._issue_tokens(int(user_id))
        return TokenPair(access_token=access, refresh_token=new_refresh)

    async def logout(self, refresh_token: str) -> None:
        await self.redis.delete(f"refresh:{refresh_token}")

    async def _issue_tokens(self, user_id: int) -> tuple[str, str]:
        access = create_access_token(user_id, self.settings.jwt_secret,
                                     self.settings.access_token_ttl_minutes)
        refresh = generate_refresh_token()
        await self.redis.setex(f"refresh:{refresh}",
                               self.settings.refresh_token_ttl_days * 86400, str(user_id))
        return access, refresh
