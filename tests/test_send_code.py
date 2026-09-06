import pytest
from fakeredis.aioredis import FakeRedis

from app.core.config import Settings
from app.core.errors import RateLimitedError
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
