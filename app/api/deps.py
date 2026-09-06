from collections.abc import AsyncIterator
from functools import lru_cache

import redis.asyncio
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.redis import get_redis_client
from app.db.session import get_engine, get_session_factory
from app.providers import make_sms_provider
from app.repositories.user_repo import UserRepo
from app.services.auth_service import AuthService


@lru_cache
def get_settings() -> Settings:
    return Settings()


_engine = None
_session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        settings = get_settings()
        _engine = get_engine(settings.database_url)
        _session_factory = get_session_factory(_engine)
    async with _session_factory() as session:
        yield session


_redis: redis.asyncio.Redis | None = None


async def get_redis() -> redis.asyncio.Redis:
    global _redis
    if _redis is None:
        _redis = get_redis_client(get_settings().redis_url)
    return _redis


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    redis: redis.asyncio.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    provider = make_sms_provider(settings.sms_provider)
    return AuthService(user_repo=UserRepo(session), sms_provider=provider,
                       redis=redis, settings=settings)
