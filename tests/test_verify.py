import asyncio
import tempfile

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidCodeError, TooManyAttemptsError
from app.core.security import decode_access_token
from app.db.models import Base, User
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
    """成功验证清除验证码与失败计数。

    调整（验证码原子消费语义）：错误尝试作废验证码后需重新发码，
    故此处在成功尝试前重新发一次码，成功后同一码不得二次使用。
    """
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000005", "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify("13800000005", "000000")
    await store_code(redis, "13800000005", "123456")  # 重新发码
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


async def test_fail_counter_ttl_self_heals_when_missing(session, provider, redis, settings):
    """TTL 自愈：若失败计数键已存在但丢失 TTL（expire 丢失的残留键），
    下一次失败必须补上过期时间——否则计数器永不过期，用户被永久锁定。"""
    svc = make_service(session, provider, redis, settings)
    phone = "13800000011"
    await redis.set(f"sms:fail:{phone}", "3")  # 无 ex 的残留键（模拟 expire 丢失）
    assert await redis.ttl(f"sms:fail:{phone}") == -1  # 存在但无 TTL
    await store_code(redis, phone, "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify(phone, "000000")
    assert (await redis.get(f"sms:fail:{phone}")).decode() == "4"
    assert await redis.ttl(f"sms:fail:{phone}") > 0, "无 TTL 的残留键未被后续失败自愈补上过期时间"


async def test_verify_wrong_attempt_consumes_code(session, provider, redis, settings):
    """验证码原子消费（GETDEL）语义：错误尝试也会作废验证码，
    之后即使输入正确码也无效，需重新发码——一次性验证码下错的尝试作废重发。"""
    svc = make_service(session, provider, redis, settings)
    phone = "13800000012"
    await store_code(redis, phone, "123456")
    with pytest.raises(InvalidCodeError):
        await svc.verify(phone, "000000")
    # 错误尝试已原子消耗验证码
    assert await redis.get(f"sms:code:{phone}") is None
    # 正确码也已作废，必须重新发码
    with pytest.raises(InvalidCodeError):
        await svc.verify(phone, "123456")


async def test_verify_concurrent_new_user_race(session, provider, redis, settings):
    """并发注册竞态：两个请求同时为新手机号通过验证（各自持有效码），
    后提交者因 unique 约束抛 IntegrityError 时必须被捕获并降级为
    "返回已存在用户"（is_new=False），不得 500；两者 user_id 一致、is_new 恰一个为 True。

    真实部署中每个请求持有独立 DB session，故用文件型 sqlite 建两个 session；
    对 get_by_phone 注入 sleep(0) 强制双协程都在 None 检查后才执行 create。
    """
    with tempfile.TemporaryDirectory() as tmp:
        engine = get_engine(f"sqlite+aiosqlite:///{tmp}/race.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = get_session_factory(engine)
        phone = "13800000013"
        await store_code(redis, phone, "123456")

        original_getdel = redis.getdel

        async def shared_getdel(key):
            # 本测试聚焦 create 竞态：验证码阶段原子性由
            # test_verify_wrong_attempt_consumes_code 锁定，此处模拟
            # 两个请求各自持有一份有效验证码（如两台设备各收到一码）。
            if key == f"sms:code:{phone}":
                return await redis.get(key)
            return await original_getdel(key)

        redis.getdel = shared_getdel

        async def make_slow_service() -> tuple[AuthService, AsyncSession]:
            s = factory()
            svc = AuthService(user_repo=UserRepo(s), sms_provider=provider,
                              redis=redis, settings=settings)
            original_get_by_phone = svc.user_repo.get_by_phone

            async def slow_get_by_phone(p):
                user = await original_get_by_phone(p)
                if user is None:
                    await asyncio.sleep(0)  # 双协程都通过 None 检查后再让出
                return user

            svc.user_repo.get_by_phone = slow_get_by_phone
            return svc, s

        svc_a, session_a = await make_slow_service()
        svc_b, session_b = await make_slow_service()
        try:
            results = await asyncio.gather(
                svc_a.verify(phone, "123456"), svc_b.verify(phone, "123456"),
                return_exceptions=True,
            )
        finally:
            await session_a.close()
            await session_b.close()
            await engine.dispose()

        errors = [r for r in results if isinstance(r, Exception)]
        assert not errors, f"并发 verify 不应失败（IntegrityError 未被捕获？）: {errors!r}"
        assert results[0].user_id == results[1].user_id
        assert sorted(r.is_new for r in results) == [False, True]

        # 数据库中只有一个用户
        check_engine = get_engine(f"sqlite+aiosqlite:///{tmp}/race.db")
        try:
            async with check_engine.connect() as conn:
                count = (await conn.execute(
                    select(func.count()).select_from(User.__table__)
                )).scalar()
        finally:
            await check_engine.dispose()
        assert count == 1
