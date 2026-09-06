import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base, User
from app.db.session import get_engine, get_session_factory
from app.repositories.user_repo import UserRepo


@pytest.fixture
async def session() -> AsyncSession:
    engine = get_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_create_and_get_by_phone(session: AsyncSession):
    repo = UserRepo(session)
    created = await repo.create("13800000001")
    assert created.id is not None
    assert created.phone == "13800000001"

    found = await repo.get_by_phone("13800000001")
    assert found is not None
    assert found.id == created.id


async def test_get_by_phone_missing(session: AsyncSession):
    repo = UserRepo(session)
    assert await repo.get_by_phone("13900000000") is None


async def test_get_by_id(session: AsyncSession):
    repo = UserRepo(session)
    created = await repo.create("13800000002")
    found = await repo.get_by_id(created.id)
    assert found is not None and found.phone == "13800000002"
    assert await repo.get_by_id(99999) is None


async def test_create_duplicate_phone_raises(session: AsyncSession):
    repo = UserRepo(session)
    await repo.create("13800000003")
    with pytest.raises(Exception):
        await repo.create("13800000003")
