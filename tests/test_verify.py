import asyncio

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidCodeError, TooManyAttemptsError
from app.core.security import decode_access_token
from app.db.models import Base
from app.db.session import get_engine, get_session_factory
from app.providers.mock import MockSmsProvider
from app.repositories.user_repo import UserRepo
from app.services.auth_service import AuthService


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret="test-secret")


@pytest.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def session() -> AsyncSession:
    engine = get_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def provider() -> MockSmsProvider:
    return MockSmsProvider()


def make_service(session, provider, redis, settings) -> AuthService:
    return AuthService(user_repo=UserRepo(session), sms_provider=provider,
                       redis=redis, settings=settings)


async def store_code(redis, phone: str, code: str) -> None:
    await redis.set(f"sms:code:{phone}", code, ex=300)


async def test_verify_new_user_registers_and_returns_tokens(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000001", "123456")
    result = await svc.verify("13800000001", "123456")
    assert result.is_new is True
    assert result.user_id > 0
    assert decode_access_token(result.access_token, settings.jwt_secret) == result.user_id
    # refresh token 已写入 redis
    assert (_ := await redis.get(f"refresh:{result.refresh_token}"))
    assert (await redis.get(f"refresh:{result.refresh_token}")).decode() == str(result.user_id)


async def test_verify_existing_user_no_reregister(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000002", "123456")
    first = await svc.verify("13800000002", "123456")
    await store_code(redis, "13800000002", "654321")
    second = await svc.verify("13800000002", "654321")
    assert second.is_new is False
    assert second.user_id == first.user_id


async def test_verify_wrong_code_raises_and_counts(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000003", "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify("13800000003", "000000")
    assert (await redis.get("sms:fail:13800000003")).decode() == "1"


async def test_verify_locked_after_max_failures(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    for i in range(settings.sms_max_fail_count):
        await store_code(redis, "13800000004", "123456")
        with pytest.raises(InvalidCodeError):
            await svc.verify("13800000004", "000000")
    with pytest.raises(TooManyAttemptsError):
        await store_code(redis, "13800000004", "123456")
        await svc.verify("13800000004", "123456")  # 即使验证码正确也锁定


async def test_verify_success_clears_code_and_fails(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000005", "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify("13800000005", "000000")
    result = await svc.verify("13800000005", "123456")
    assert result.is_new is True
    # 验证码一次性：成功后即删除，同一验证码不能二次使用
    assert await redis.get("sms:code:13800000005") is None
    assert await redis.get("sms:fail:13800000005") is None
    with pytest.raises(InvalidCodeError):
        await svc.verify("13800000005", "123456")


async def test_verify_missing_code_raises(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    with pytest.raises(InvalidCodeError):
        await svc.verify("13800000006", "123456")


async def test_fail_counter_ttl_set_only_on_first_failure(session, provider, redis, settings):
    """锁定窗口从首次失败起算（TTL 只在计数器首次创建时设置，不随后续失败重置）。

    预置一个接近上限的失败计数（TTL 已明显小于完整窗口），
    再次失败后计数 +1 但 TTL 不得被重置回完整窗口——
    否则攻击者持续失败会让锁定永不自清。
    """
    svc = make_service(session, provider, redis, settings)
    phone = "13800000008"
    await redis.set(f"sms:fail:{phone}", "4", ex=10)  # TTL 10s < sms_code_ttl_seconds(300)
    await store_code(redis, phone, "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify(phone, "000000")
    assert (await redis.get(f"sms:fail:{phone}")).decode() == "5"
    ttl = await redis.ttl(f"sms:fail:{phone}")
    assert 0 < ttl <= 10, f"失败计数 TTL 被重置（{ttl}），锁定窗口可被无限推迟"


async def test_fail_counter_ttl_created_on_first_failure(session, provider, redis, settings):
    """首次失败时计数器必须带上过期时间（无 TTL 的残留键不允许出现）。"""
    svc = make_service(session, provider, redis, settings)
    phone = "13800000009"
    await store_code(redis, phone, "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify(phone, "000000")
    ttl = await redis.ttl(f"sms:fail:{phone}")
    assert ttl == settings.sms_code_ttl_seconds or 0 < ttl <= settings.sms_code_ttl_seconds


async def test_fail_counter_expires_allowing_retry_after_window(session, provider, redis, settings):
    """窗口过期后计数器自清，用户可再次尝试（首错起 5 分钟语义）。"""
    svc = make_service(session, provider, redis, settings)
    phone = "13800000010"
    await redis.set(f"sms:fail:{phone}", str(settings.sms_max_fail_count), ex=1)
    await asyncio.sleep(1.1)  # 模拟锁定窗口流逝
    await store_code(redis, phone, "123456")
    result = await svc.verify(phone, "123456")  # 不再抛 TooManyAttemptsError
    assert result.is_new is True
