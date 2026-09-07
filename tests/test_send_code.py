import asyncio

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.config import Settings
from app.core.errors import RateLimitedError, TooManyAttemptsError
from app.providers.mock import MockSmsProvider
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
def provider() -> MockSmsProvider:
    return MockSmsProvider()


async def test_send_code_stores_code_and_calls_provider(redis, provider, settings):
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)
    expires_in = await svc.send_code("13800000001")
    assert expires_in == settings.sms_code_ttl_seconds
    stored = await redis.get("sms:code:13800000001")
    assert stored is not None and len(stored.decode()) == 6 and stored.decode().isdigit()
    assert provider.sent[0][0] == "13800000001"
    assert provider.sent[0][1] == stored.decode()
    ttl = await redis.ttl("sms:code:13800000001")
    assert 0 < ttl <= settings.sms_code_ttl_seconds


async def test_send_code_rate_limited(redis, provider, settings):
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)
    await svc.send_code("13800000002")
    with pytest.raises(RateLimitedError):
        await svc.send_code("13800000002")
    assert len(provider.sent) == 1


async def test_rate_limit_key_ttl(redis, provider, settings):
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)
    await svc.send_code("13800000003")
    ttl = await redis.ttl("sms:limit:13800000003")
    assert 0 < ttl <= settings.sms_send_limit_seconds


async def test_different_phones_not_limited(redis, provider, settings):
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)
    await svc.send_code("13800000004")
    await svc.send_code("13800000005")  # 不应抛错
    assert len(provider.sent) == 2


async def test_send_code_concurrent_only_one_wins(redis, provider, settings):
    """限流检查与写入必须原子（SET NX）：并发双请求只放行一个。

    fakeredis 命令不会真正挂起协程，因此通过在旧实现的
    exists 检查通过之后注入 sleep(0) 强制事件循环切换，
    模拟真实 Redis 网络延迟下"双请求同时通过 exists 检查"的交错。
    """
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)

    original_exists = redis.exists

    async def slow_exists(*keys):
        result = await original_exists(*keys)
        if result == 0:
            await asyncio.sleep(0)  # 检查通过后、写入限流键前让出控制权
        return result

    redis.exists = slow_exists

    results = await asyncio.gather(
        svc.send_code("13800000006"), svc.send_code("13800000006"),
        return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(ok) == 1, f"预期恰好一次发码成功，实际 {results}"
    assert len(errors) == 1 and isinstance(errors[0], RateLimitedError)
    assert len(provider.sent) == 1


async def test_rate_limit_key_is_nx_semaphore(redis, provider, settings):
    """限流键语义：写入成功者才放行（返回值判断，而非 exists 预检查）。"""
    # 已存在的限流键 → SET NX 失败 → RateLimited
    await redis.set("sms:limit:13800000007", "1", ex=60)
    svc = AuthService(user_repo=None, sms_provider=provider, redis=redis, settings=settings)
    with pytest.raises(RateLimitedError):
        await svc.send_code("13800000007")
    assert len(provider.sent) == 0
    # 限流键的 TTL 不被后续拒绝的请求刷新
    ttl_before = await redis.ttl("sms:limit:13800000007")
    with pytest.raises(RateLimitedError):
        await svc.send_code("13800000007")
    assert await redis.ttl("sms:limit:13800000007") == ttl_before
