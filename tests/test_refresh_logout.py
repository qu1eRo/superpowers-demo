import pytest
from fakeredis.aioredis import FakeRedis

from app.core.config import Settings
from app.core.errors import InvalidTokenError
from app.core.security import decode_access_token
from app.services.auth_service import AuthService


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret="test-secret")


@pytest.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


def make_service(redis, settings) -> AuthService:
    return AuthService(user_repo=None, sms_provider=None, redis=redis, settings=settings)


@pytest.fixture
async def issued_token(redis, settings):
    svc = make_service(redis, settings)
    access, refresh = await svc._issue_tokens(42)
    return access, refresh


async def test_refresh_rotates_tokens(redis, settings, issued_token):
    old_access, old_refresh = issued_token
    svc = make_service(redis, settings)
    pair = await svc.refresh(old_refresh)
    assert pair.token_type == "bearer"
    assert pair.refresh_token != old_refresh
    assert decode_access_token(pair.access_token, settings.jwt_secret) == 42
    # 旧 refresh token 已失效
    assert await redis.get(f"refresh:{old_refresh}") is None
    assert (await redis.get(f"refresh:{pair.refresh_token}")).decode() == "42"
    # 新 token 可再次刷新（链式轮换）
    pair2 = await svc.refresh(pair.refresh_token)
    assert pair2.refresh_token != pair.refresh_token


async def test_refresh_unknown_token_raises(redis, settings):
    svc = make_service(redis, settings)
    with pytest.raises(InvalidTokenError):
        await svc.refresh("no-such-token")


async def test_logout_revokes(redis, settings, issued_token):
    _, refresh = issued_token
    svc = make_service(redis, settings)
    await svc.logout(refresh)
    assert await redis.get(f"refresh:{refresh}") is None
    with pytest.raises(InvalidTokenError):
        await svc.refresh(refresh)


async def test_logout_idempotent(redis, settings):
    svc = make_service(redis, settings)
    await svc.logout("never-existed")  # 不抛错
