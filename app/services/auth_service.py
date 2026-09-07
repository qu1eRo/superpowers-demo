import secrets

import redis.asyncio
from sqlalchemy.exc import IntegrityError

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
        code = f"{secrets.randbelow(10**6):06d}"
        # 限流：SET NX EX 原子获取信号量，写入成功者放行，已被限流则拒绝。
        acquired = await self.redis.set(
            f"sms:limit:{phone}", "1",
            nx=True, ex=self.settings.sms_send_limit_seconds,
        )
        if acquired is None:
            raise RateLimitedError()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(f"sms:code:{phone}", code, ex=self.settings.sms_code_ttl_seconds)
            await pipe.execute()
        await self.sms_provider.send_code(phone, code)
        return self.settings.sms_code_ttl_seconds

    async def verify(self, phone: str, code: str) -> VerifyResponse:
        fail_key = f"sms:fail:{phone}"
        fails = int(_get_str(await self.redis.get(fail_key)) or 0)
        if fails >= self.settings.sms_max_fail_count:
            raise TooManyAttemptsError()

        # GETDEL 原子消费验证码（一次性语义）：读到即作废，消除 get -> delete
        # 间隙的并发复用窗口。错误尝试同样消耗验证码——错的尝试作废、
        # 重新发码是一次性验证码下的常见设计。
        stored = _get_str(await self.redis.getdel(f"sms:code:{phone}"))
        if stored is None or stored != code:
            # 失败计数：incr 返回 1（首次）时设置过期；若首次的 expire
            # 丢失导致键存在但无 TTL（ttl() == -1），任何后续失败都会补上，
            # 自愈防止计数器永不过期造成用户永久锁定。窗口仍从首次失败
            # 起算，不随后续失败重置（否则可被无限推迟）。
            fails = await self.redis.incr(fail_key)
            if fails == 1 or await self.redis.ttl(fail_key) == -1:
                await self.redis.expire(fail_key, self.settings.sms_code_ttl_seconds)
            raise InvalidCodeError()

        await self.redis.delete(fail_key)

        user = await self.user_repo.get_by_phone(phone)
        is_new = user is None
        if is_new:
            try:
                user = await self.user_repo.create(phone)
            except IntegrityError:
                # 并发注册竞态：另一请求已抢先插入同手机号（unique 约束）。
                # 回滚后返回已存在用户，is_new 以"本次请求是否真的创建了"判定。
                await self.user_repo.session.rollback()
                user = await self.user_repo.get_by_phone(phone)
                if user is None:
                    raise
                is_new = False

        access, refresh = await self._issue_tokens(user.id)
        return VerifyResponse(access_token=access, refresh_token=refresh,
                              user_id=user.id, is_new=is_new)

    async def refresh(self, refresh_token: str) -> TokenPair:
        key = f"refresh:{refresh_token}"
        # GETDEL 原子获取并吊销，消除 get -> delete 间隙的轮换复用窗口。
        user_id = _get_str(await self.redis.getdel(key))
        if user_id is None:
            raise InvalidTokenError()
        access, new_refresh = await self._issue_tokens(int(user_id))
        return TokenPair(access_token=access, refresh_token=new_refresh)

    async def logout(self, refresh_token: str) -> None:
        await self.redis.delete(f"refresh:{refresh_token}")

    async def _issue_tokens(self, user_id: int) -> tuple[str, str]:
        access = create_access_token(user_id, self.settings.jwt_secret,
                                     self.settings.access_token_ttl_minutes)
        refresh = generate_refresh_token()
        await self.redis.set(f"refresh:{refresh}", str(user_id),
                             ex=self.settings.refresh_token_ttl_days * 86400)
        return access, refresh
