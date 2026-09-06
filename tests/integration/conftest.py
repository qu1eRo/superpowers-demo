import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_service, get_redis, get_settings, get_session
from app.core.config import Settings
from app.db.models import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.providers.mock import MockSmsProvider
from app.repositories.user_repo import UserRepo
from app.services.auth_service import AuthService


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret="test-secret")


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
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def provider() -> MockSmsProvider:
    return MockSmsProvider()


@pytest.fixture
async def client(session, redis, provider, settings):
    app = create_app()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session

    async def override_redis():
        return redis

    app.dependency_overrides[get_redis] = override_redis
    app.dependency_overrides[get_settings] = lambda: settings

    def override_service():
        return AuthService(user_repo=UserRepo(session), sms_provider=provider,
                           redis=redis, settings=settings)

    app.dependency_overrides[get_auth_service] = override_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
