# 手机号验证登录 API 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基于手机号短信验证码的登录/注册一体化 REST API（FastAPI + PostgreSQL + Redis），首次验证自动注册，签发 JWT access token + 可吊销 refresh token。

**Architecture:** 单体分层：`routers`（HTTP 校验）→ `services`（业务规则）→ `repositories`（数据库）/ `providers`（短信）。短信服务商为可插拔接口，开发默认 mock（验证码打印到控制台）。依赖通过 FastAPI `Depends` 注入，测试中全部可替换。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy 2.0 (asyncio)、asyncpg、redis-py (async)、PyJWT、pydantic-settings；测试用 pytest、pytest-asyncio、httpx、fakeredis、aiosqlite。

**Spec:** `docs/superpowers/specs/2026-09-06-phone-auth-api-design.md`

## Global Constraints

- Python `>=3.11`；包管理用 venv + pip（Windows：`.venv\Scripts\python`）。
- 所有异步测试通过 `pytest-asyncio` 的 `asyncio_mode = "auto"` 运行，无需逐个加装饰器。
- 单元/集成测试一律不依赖真实 PostgreSQL/Redis：数据库用 aiosqlite（内存），Redis 用 fakeredis。生产连接串只出现在配置默认值和 `.env.example`。
- 统一错误响应格式 `{"code": "...", "message": "..."}`，业务错误一律抛 `AppError` 子类，由全局 handler 转换。
- Redis 键名严格按 spec：`sms:code:{phone}`、`sms:limit:{phone}`、`sms:fail:{phone}`、`refresh:{token}`。
- 手机号校验正则 `^1[3-9]\d{9}$`；验证码为 6 位数字字符串（不足补零，如 `"004237"`）。
- 每个任务结束都要 commit；运行命令统一用 `python -m pytest ... -v`（在仓库根目录、激活 venv 后执行）。
- 测试中 JWT 密钥固定 `test-secret`；`Settings` 在测试里直接以关键字参数构造，不读 `.env`。

---

### Task 1: 项目脚手架 + 配置 + 健康检查

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`（空）
- Create: `app/core/__init__.py`（空）
- Create: `app/core/config.py`
- Create: `app/main.py`
- Test: `tests/__init__.py`（空）、`tests/conftest.py`、`tests/test_main.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `Settings` 类（`app/core/config.py`），字段：`sms_provider: str = "mock"`、`database_url: str`、`redis_url: str = "redis://localhost:6379/0"`、`jwt_secret: str`（必填无默认）、`access_token_ttl_minutes: int = 30`、`refresh_token_ttl_days: int = 30`、`sms_code_ttl_seconds: int = 300`、`sms_send_limit_seconds: int = 60`、`sms_max_fail_count: int = 5`；构造方式 `Settings(jwt_secret="test-secret")`（pydantic-settings，读环境变量/`.env`）。FastAPI 应用工厂 `create_app() -> FastAPI`（`app/main.py`）。

- [ ] **Step 1: 创建 venv 并安装依赖骨架**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
```

- [ ] **Step 2: 写 pyproject.toml**

```toml
[project]
name = "superpower-demo"
version = "0.1.0"
description = "手机号验证登录 API demo"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "redis>=5.0",
    "pyjwt>=2.9",
    "pydantic-settings>=2.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "fakeredis>=2.24",
    "aiosqlite>=0.20",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

安装：`.venv/Scripts/python -m pip install -e ".[dev]"`

- [ ] **Step 3: 写失败测试**

`tests/conftest.py`（设置环境变量必须在导入 app 之前）：

```python
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
```

`tests/test_main.py`：

```python
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_check():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_settings_defaults():
    s = Settings(jwt_secret="k")
    assert s.sms_provider == "mock"
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.access_token_ttl_minutes == 30
    assert s.refresh_token_ttl_days == 30
    assert s.sms_code_ttl_seconds == 300
    assert s.sms_send_limit_seconds == 60
    assert s.sms_max_fail_count == 5
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app'` 或导入错误）

- [ ] **Step 5: 实现**

`app/core/config.py`：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    sms_provider: str = "mock"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/superpower_demo"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    sms_code_ttl_seconds: int = 300
    sms_send_limit_seconds: int = 60
    sms_max_fail_count: int = 5
```

`app/main.py`：

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Phone Auth API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_main.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml app tests
git commit -m "feat: 项目脚手架、配置与健康检查"
```

---

### Task 2: 错误模型 + 全局异常处理

**Files:**
- Create: `app/core/errors.py`
- Modify: `app/main.py`（注册 handler）
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `create_app()`（Task 1）
- Produces: `app/core/errors.py` 中的异常类，后续所有 service/router 抛出：
  - `AppError(Exception)`：属性 `status: int`、`code: str`、`message: str`
  - `RateLimitedError` → `429, "RATE_LIMITED", "发送过于频繁，请稍后再试"`
  - `TooManyAttemptsError` → `429, "TOO_MANY_ATTEMPTS", "尝试次数过多，请稍后再试"`
  - `InvalidCodeError` → `400, "INVALID_CODE", "验证码错误或已过期"`
  - `InvalidTokenError` → `401, "INVALID_TOKEN", "令牌无效或已过期"`
  - `InternalError` → `500, "INTERNAL_ERROR", "内部错误"`

- [ ] **Step 1: 写失败测试**

`tests/test_errors.py`：

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    AppError,
    InvalidCodeError,
    InvalidTokenError,
    RateLimitedError,
    TooManyAttemptsError,
)
from app.main import create_app


def _app_with_error_route(exc: Exception) -> FastAPI:
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise exc

    return app


def test_error_response_format():
    cases = [
        (RateLimitedError(), 429, "RATE_LIMITED"),
        (TooManyAttemptsError(), 429, "TOO_MANY_ATTEMPTS"),
        (InvalidCodeError(), 400, "INVALID_CODE"),
        (InvalidTokenError(), 401, "INVALID_TOKEN"),
    ]
    for exc, status, code in cases:
        client = TestClient(_app_with_error_route(exc), raise_server_exceptions=False)
        resp = client.get("/boom")
        assert resp.status_code == status
        body = resp.json()
        assert set(body) == {"code", "message"}
        assert body["code"] == code


def test_unhandled_error_is_500_without_traceback():
    app = _app_with_error_route(RuntimeError("boom detail"))
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert "boom detail" not in resp.text
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_errors.py -v`
Expected: FAIL（`No module named 'app.core.errors'`）

- [ ] **Step 3: 实现**

`app/core/errors.py`：

```python
class AppError(Exception):
    status: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "内部错误"


class RateLimitedError(AppError):
    status, code, message = 429, "RATE_LIMITED", "发送过于频繁，请稍后再试"


class TooManyAttemptsError(AppError):
    status, code, message = 429, "TOO_MANY_ATTEMPTS", "尝试次数过多，请稍后再试"


class InvalidCodeError(AppError):
    status, code, message = 400, "INVALID_CODE", "验证码错误或已过期"


class InvalidTokenError(AppError):
    status, code, message = 401, "INVALID_TOKEN", "令牌无效或已过期"


class InternalError(AppError):
    status, code, message = 500, "INTERNAL_ERROR", "内部错误"
```

修改 `app/main.py`，在 `create_app()` 内注册两个 handler（放在 `/health` 路由之前）：

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError


def create_app() -> FastAPI:
    app = FastAPI(title="Phone Auth API", version="0.1.0")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "内部错误"})

    # ...原有 /health 路由...
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_errors.py tests/test_main.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/errors.py app/main.py tests/test_errors.py
git commit -m "feat: 统一错误模型与全局异常处理"
```

---

### Task 3: User 模型 + UserRepo + 异步会话工厂

**Files:**
- Create: `app/db/__init__.py`（空）
- Create: `app/db/models.py`
- Create: `app/db/session.py`
- Create: `app/repositories/__init__.py`（空）
- Create: `app/repositories/user_repo.py`
- Test: `tests/test_user_repo.py`

**Interfaces:**
- Consumes: `Settings.database_url`（Task 1）
- Produces:
  - `app/db/models.py`：`Base`（`DeclarativeBase`）与 `User` ORM 模型（表 `users`，列 `id`/`phone`/`created_at`/`updated_at`，`phone` 唯一索引）
  - `app/db/session.py`：`get_engine(database_url: str) -> AsyncEngine`、`get_session_factory(engine: AsyncSession) -> async_sessionmaker[AsyncSession]`（`expire_on_commit=False`）
  - `app/repositories/user_repo.py`：`UserRepo(session: AsyncSession)`，方法 `async def get_by_phone(phone: str) -> User | None`、`async def get_by_id(user_id: int) -> User | None`、`async def create(phone: str) -> User`

- [ ] **Step 1: 写失败测试**

`tests/test_user_repo.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_repo.py -v`
Expected: FAIL（`No module named 'app.db'`）

- [ ] **Step 3: 实现**

`app/db/models.py`：

```python
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

`app/db/session.py`：

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def get_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, echo=False)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

`app/repositories/user_repo.py`：

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def create(self, phone: str) -> User:
        user = User(phone=phone)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_user_repo.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/db app/repositories tests/test_user_repo.py
git commit -m "feat: User 模型、异步会话工厂与 UserRepo"
```

---

### Task 4: SmsProvider 接口 + mock + aliyun stub + 工厂

**Files:**
- Create: `app/providers/__init__.py`（内容见下）
- Create: `app/providers/base.py`
- Create: `app/providers/mock.py`
- Create: `app/providers/aliyun.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `SmsProvider`（ABC，`app/providers/base.py`）：`async def send_code(self, phone: str, code: str) -> None`
  - `MockSmsProvider`：发送记录存 `self.sent: list[tuple[str, str]]`，同时 `print` 到控制台（格式 `[MOCK SMS] {phone} -> {code}`）
  - `AliyunSmsProvider`：`send_code` 抛 `NotImplementedError("阿里云短信尚未接入")`
  - 工厂 `make_sms_provider(name: str) -> SmsProvider`（`app/providers/__init__.py`）：`"mock"` → Mock，`"aliyun"` → Aliyun，其他值抛 `ValueError`

- [ ] **Step 1: 写失败测试**

`tests/test_providers.py`：

```python
import pytest

from app.providers import AliyunSmsProvider, MockSmsProvider, make_sms_provider
from app.providers.base import SmsProvider


async def test_mock_provider_records_send():
    p = MockSmsProvider()
    await p.send_code("13800000001", "004237")
    assert p.sent == [("13800000001", "004237")]


async def test_mock_provider_is_sms_provider():
    assert isinstance(MockSmsProvider(), SmsProvider)


async def test_aliyun_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await AliyunSmsProvider().send_code("13800000001", "004237")


def test_factory_selects_provider():
    assert isinstance(make_sms_provider("mock"), MockSmsProvider)
    assert isinstance(make_sms_provider("aliyun"), AliyunSmsProvider)


def test_factory_unknown_name_raises():
    with pytest.raises(ValueError):
        make_sms_provider("twilio")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_providers.py -v`
Expected: FAIL（`No module named 'app.providers'`）

- [ ] **Step 3: 实现**

`app/providers/base.py`：

```python
from abc import ABC, abstractmethod


class SmsProvider(ABC):
    @abstractmethod
    async def send_code(self, phone: str, code: str) -> None:
        """发送验证码短信。实现方应自行处理重试与异常上报。"""
```

`app/providers/mock.py`：

```python
from app.providers.base import SmsProvider


class MockSmsProvider(SmsProvider):
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_code(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))
        print(f"[MOCK SMS] {phone} -> {code}")
```

`app/providers/aliyun.py`：

```python
from app.providers.base import SmsProvider


class AliyunSmsProvider(SmsProvider):
    async def send_code(self, phone: str, code: str) -> None:
        raise NotImplementedError("阿里云短信尚未接入")
```

`app/providers/__init__.py`：

```python
from app.providers.aliyun import AliyunSmsProvider
from app.providers.base import SmsProvider
from app.providers.mock import MockSmsProvider


def make_sms_provider(name: str) -> SmsProvider:
    if name == "mock":
        return MockSmsProvider()
    if name == "aliyun":
        return AliyunSmsProvider()
    raise ValueError(f"未知的短信服务商: {name}")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_providers.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/providers tests/test_providers.py
git commit -m "feat: 可插拔短信 Provider 接口与 mock 实现"
```

---

### Task 5: JWT 安全模块

**Files:**
- Create: `app/core/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: 无
- Produces（`app/core/security.py`）：
  - `create_access_token(user_id: int, secret: str, ttl_minutes: int) -> str`（HS256，payload 含 `sub=str(user_id)`、`exp`）
  - `decode_access_token(token: str, secret: str) -> int`（无效/过期抛 `jwt.InvalidTokenError`，即 `PyJWTError` 子类）
  - `generate_refresh_token() -> str`（`secrets.token_urlsafe(48)`，每次不同）

- [ ] **Step 1: 写失败测试**

`tests/test_security.py`：

```python
import jwt
import pytest

from app.core.security import create_access_token, decode_access_token, generate_refresh_token


def test_access_token_roundtrip():
    token = create_access_token(42, "secret", 30)
    assert decode_access_token(token, "secret") == 42


def test_expired_token_raises():
    token = create_access_token(42, "secret", -1)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "secret")


def test_wrong_secret_raises():
    token = create_access_token(42, "secret", 30)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "other")


def test_refresh_tokens_unique():
    assert generate_refresh_token() != generate_refresh_token()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_security.py -v`
Expected: FAIL（`No module named 'app.core.security'`）

- [ ] **Step 3: 实现**

`app/core/security.py`：

```python
import secrets
from datetime import datetime, timedelta, timezone

import jwt


def create_access_token(user_id: int, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "exp": now + timedelta(minutes=ttl_minutes), "iat": now}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> int:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    return int(payload["sub"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_security.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/test_security.py
git commit -m "feat: JWT 签发/校验与 refresh token 生成"
```

---

### Task 6: AuthService.send_code（发送 + 频率限制）

**Files:**
- Create: `app/services/__init__.py`（空）
- Create: `app/services/auth_service.py`
- Test: `tests/test_send_code.py`

**Interfaces:**
- Consumes: `UserRepo`（Task 3）、`SmsProvider`（Task 4）、`Settings`（Task 1）、`RateLimitedError`（Task 2）
- Produces: `AuthService(user_repo: UserRepo, sms_provider: SmsProvider, redis: redis.asyncio.Redis, settings: Settings)`，方法：
  - `async def send_code(self, phone: str) -> int`：返回 `settings.sms_code_ttl_seconds`；频率受限时抛 `RateLimitedError`
  - Redis 值统一以 `str` 读写（fake/real redis 混用时的 bytes 由 `_get_str` 帮助函数处理）

- [ ] **Step 1: 写失败测试**

`tests/test_send_code.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_send_code.py -v`
Expected: FAIL（`No module named 'app.services'`）

- [ ] **Step 3: 实现**

`app/services/auth_service.py`：

```python
import secrets

import redis.asyncio

from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.core.security import create_access_token, generate_refresh_token
from app.providers.base import SmsProvider
from app.repositories.user_repo import UserRepo


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
```

（`create_access_token`/`generate_refresh_token` 的 import 在 Task 7 使用，先一并导入会触发未使用告警——本任务只导入当前需要的，Task 7 再补充。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_send_code.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services tests/test_send_code.py
git commit -m "feat: 发送验证码与频率限制"
```

---

### Task 7: AuthService.verify（验证 + 自动注册 + 签发 token）

**Files:**
- Modify: `app/services/auth_service.py`（新增 `verify` 方法与 `VerifyResult`）
- Create: `app/schemas/__init__.py`（空）、`app/schemas/auth.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: Task 3/4/5/6 的全部接口
- Produces:
  - `app/schemas/auth.py`：`TokenPair`（`access_token: str`、`refresh_token: str`、`token_type: str = "bearer"`）、`VerifyResponse(TokenPair)`（`user_id: int`、`is_new: bool`）
  - `AuthService.verify(phone: str, code: str) -> VerifyResponse`
  - 行为：达到 `sms_max_fail_count` 抛 `TooManyAttemptsError`；验证码不匹配/不存在抛 `InvalidCodeError` 并递增 `sms:fail:{phone}`（TTL = `sms_code_ttl_seconds`）；成功后删除 `sms:code:` 与 `sms:fail:` 键，查/建用户，写 `refresh:{token}`（TTL = `refresh_token_ttl_days * 86400` 秒）

- [ ] **Step 1: 写失败测试**

`tests/test_verify.py`：

```python
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
    await redis.setex(f"sms:code:{phone}", 300, code)


async def test_verify_new_user_registers_and_returns_tokens(session, provider, redis, settings):
    svc = make_service(session, provider, redis, settings)
    await store_code(redis, "13800000001", "123456")
    result = await svc.verify("13800000001", "123456")
    assert result.is_new is True
    assert result.user_id > 0
    assert decode_access_token(result.access_token, settings.jwt_secret) == result.user_id
    # refresh token 已写入 redis
    assert _ := await redis.get(f"refresh:{result.refresh_token}")
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL（`ImportError: cannot import name 'verify'` 或 `app.schemas` 不存在）

- [ ] **Step 3: 实现**

`app/schemas/auth.py`：

```python
from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyResponse(TokenPair):
    user_id: int
    is_new: bool
```

`app/services/auth_service.py` 新增（文件顶部补充 import `InvalidCodeError, TooManyAttemptsError`、`create_access_token, generate_refresh_token`、`VerifyResponse`；`_issue_tokens` 为内部帮助方法）：

```python
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

    async def _issue_tokens(self, user_id: int) -> tuple[str, str]:
        access = create_access_token(user_id, self.settings.jwt_secret,
                                     self.settings.access_token_ttl_minutes)
        refresh = generate_refresh_token()
        await self.redis.setex(f"refresh:{refresh}",
                               self.settings.refresh_token_ttl_days * 86400, str(user_id))
        return access, refresh
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_verify.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/auth_service.py app/schemas tests/test_verify.py
git commit -m "feat: 验证码校验、自动注册与 token 签发"
```

---

### Task 8: AuthService.refresh + logout

**Files:**
- Modify: `app/services/auth_service.py`（新增两个方法）
- Test: `tests/test_refresh_logout.py`

**Interfaces:**
- Consumes: Task 7 的 `_issue_tokens`
- Produces:
  - `async def refresh(self, refresh_token: str) -> TokenPair`：不存在抛 `InvalidTokenError`；成功时删除旧 token（轮换）并返回新对
  - `async def logout(self, refresh_token: str) -> None`：删除 `refresh:{token}`，不存在也静默成功（幂等）

- [ ] **Step 1: 写失败测试**

`tests/test_refresh_logout.py`：

```python
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
    assert await redis.get(f"refresh:{pair.refresh_token}").decode() == "42"
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_refresh_logout.py -v`
Expected: FAIL（`AttributeError: 'AuthService' object has no attribute 'refresh'`）

- [ ] **Step 3: 实现**

`app/services/auth_service.py` 新增（顶部补充 `InvalidTokenError` 与 `TokenPair` 的 import）：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_refresh_logout.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/auth_service.py tests/test_refresh_logout.py
git commit -m "feat: refresh token 轮换与登出吊销"
```

---

### Task 9: 依赖注入 + 路由（send-code / verify）+ 集成测试基建

**Files:**
- Create: `app/api/__init__.py`（空）、`app/api/deps.py`
- Create: `app/routers/__init__.py`（空）、`app/routers/auth.py`
- Modify: `app/main.py`（挂载路由）、`app/db/redis.py`（新建，并入本任务）
- Modify: `app/schemas/auth.py`（补充请求模型）
- Test: `tests/integration/__init__.py`（空）、`tests/integration/conftest.py`、`tests/integration/test_auth_flow.py`

**Interfaces:**
- Consumes: 前面全部任务
- Produces:
  - `app/db/redis.py`：`get_redis_client(redis_url: str) -> redis.asyncio.Redis`
  - `app/api/deps.py`：`get_settings() -> Settings`（lru_cache）、`async def get_session() -> AsyncIterator[AsyncSession]`、`async def get_redis() -> redis.asyncio.Redis`、`async def get_auth_service(...) -> AuthService`、`async def get_current_user(...) -> User`（Task 10 用 HTTPBearer）
  - `app/routers/auth.py`：`router = APIRouter(prefix="/auth", tags=["auth"])`，端点 `POST /send-code`（202）、`POST /verify`（200，`VerifyResponse`）
  - `app/schemas/auth.py` 补充：`SendCodeRequest(phone: str)`（正则 `^1[3-9]\d{9}$`）、`VerifyRequest(phone: str, code: str)`（`code` 正则 `^\d{6}$`）、`RefreshRequest(refresh_token: str)`、`UserOut(id: int, phone: str, created_at: datetime)`
  - 集成测试 fixture：`client`（httpx `AsyncClient`，`app.dependency_overrides` 替换 session/redis/auth_service），数据库 aiosqlite 内存 + fakeredis

- [ ] **Step 1: 写失败集成测试**

`tests/integration/conftest.py`：

```python
import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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

    app.dependency_overrides[__import__("app.api.deps", fromlist=["get_session"]).get_session] = override_session
    deps = __import__("app.api.deps", fromlist=["get_redis", "get_auth_service"])
    app.dependency_overrides[deps.get_redis] = lambda: redis
    app.dependency_overrides[deps.get_settings] = lambda: settings

    def override_service():
        return AuthService(user_repo=UserRepo(session), sms_provider=provider,
                           redis=redis, settings=settings)

    app.dependency_overrides[deps.get_auth_service] = override_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

`tests/integration/test_auth_flow.py`：

```python
async def test_send_code_then_verify_full_flow(client, provider, redis):
    # 1. 发送验证码
    resp = await client.post("/auth/send-code", json={"phone": "13800000001"})
    assert resp.status_code == 202
    assert resp.json() == {"expires_in": 300}
    code = provider.sent[0][1]

    # 2. 验证登录（新用户自动注册）
    resp = await client.post("/auth/verify", json={"phone": "13800000001", "code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_new"] is True
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


async def test_send_code_rate_limited(client):
    await client.post("/auth/send-code", json={"phone": "13800000002"})
    resp = await client.post("/auth/send-code", json={"phone": "13800000002"})
    assert resp.status_code == 429
    assert resp.json()["code"] == "RATE_LIMITED"


async def test_verify_wrong_code(client):
    await client.post("/auth/send-code", json={"phone": "13800000003"})
    resp = await client.post("/auth/verify", json={"phone": "13800000003", "code": "000000"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_CODE"


async def test_invalid_phone_rejected(client):
    resp = await client.post("/auth/send-code", json={"phone": "12345"})
    assert resp.status_code == 422
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_auth_flow.py -v`
Expected: FAIL（`No module named 'app.api'` / 404）

- [ ] **Step 3: 实现**

`app/db/redis.py`：

```python
import redis.asyncio


def get_redis_client(redis_url: str) -> redis.asyncio.Redis:
    return redis.asyncio.from_url(redis_url, decode_responses=False)
```

`app/schemas/auth.py` 补充：

```python
from datetime import datetime

from pydantic import BaseModel, Field


class SendCodeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")


class VerifyRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    phone: str
    created_at: datetime
```

`app/api/deps.py`：

```python
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
```

`app/routers/auth.py`：

```python
from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service
from app.schemas.auth import SendCodeRequest, VerifyRequest, VerifyResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/send-code", status_code=202)
async def send_code(req: SendCodeRequest,
                    svc: AuthService = Depends(get_auth_service)) -> dict:
    expires_in = await svc.send_code(req.phone)
    return {"expires_in": expires_in}


@router.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest,
                 svc: AuthService = Depends(get_auth_service)) -> VerifyResponse:
    return await svc.verify(req.phone, req.code)
```

`app/main.py` 修改（`create_app()` 内，handler 注册之后）：

```python
from app.routers.auth import router as auth_router

    app.include_router(auth_router)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/integration -v`
Expected: 4 passed；随后全量 `python -m pytest -v` 确认无回归

- [ ] **Step 5: Commit**

```bash
git add app/api app/routers app/db/redis.py app/schemas tests/integration app/main.py
git commit -m "feat: 认证路由、依赖注入与集成测试基建"
```

---

### Task 10: refresh / logout / me 端点 + 认证依赖

**Files:**
- Modify: `app/routers/auth.py`（新增三个端点）
- Modify: `app/api/deps.py`（新增 `get_current_user`）
- Test: `tests/integration/test_token_endpoints.py`

**Interfaces:**
- Consumes: `AuthService.refresh/logout`（Task 8）、`decode_access_token`（Task 5）、`UserRepo.get_by_id`（Task 3）、`InvalidTokenError`（Task 2）
- Produces:
  - `POST /auth/refresh` → 200 `TokenPair`；无效 token 401 `INVALID_TOKEN`
  - `POST /auth/logout` → 204 无 body；幂等
  - `GET /auth/me` → 200 `UserOut`；Bearer access token 认证（`fastapi.security.HTTPBearer`，`auto_error=False`，缺失/无效均 401）
  - `app/api/deps.py` 新增：`async def get_current_user(credentials, session, settings) -> User`

- [ ] **Step 1: 写失败测试**

`tests/integration/test_token_endpoints.py`：

```python
from tests.integration.conftest import *  # 复用 client/provider fixture


async def _login(client, provider, phone="13800000001"):
    await client.post("/auth/send-code", json={"phone": phone})
    code = provider.sent[-1][1]
    resp = await client.post("/auth/verify", json={"phone": phone, "code": code})
    return resp.json()


async def test_me_returns_user(client, provider):
    tokens = await _login(client, provider)
    resp = await client.get("/auth/me",
                            headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == "13800000001"
    assert body["id"] == tokens["user_id"]
    assert "created_at" in body


async def test_me_without_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


async def test_me_with_garbage_token(client):
    resp = await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


async def test_refresh_rotation_via_http(client, provider):
    tokens = await _login(client, provider, "13800000002")
    resp = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_pair = resp.json()
    assert new_pair["refresh_token"] != tokens["refresh_token"]
    # 旧 refresh token 已失效
    resp2 = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp2.status_code == 401


async def test_logout_revokes_refresh(client, provider):
    tokens = await _login(client, provider, "13800000003")
    resp = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 204
    resp2 = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp2.status_code == 401


async def test_logout_idempotent_via_http(client):
    resp = await client.post("/auth/logout", json={"refresh_token": "never-existed"})
    assert resp.status_code == 204
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_token_endpoints.py -v`
Expected: FAIL（404，端点不存在）

- [ ] **Step 3: 实现**

`app/api/deps.py` 追加：

```python
import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidTokenError
from app.core.security import decode_access_token
from app.db.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise InvalidTokenError()
    try:
        user_id = decode_access_token(credentials.credentials, settings.jwt_secret)
    except jwt.InvalidTokenError:
        raise InvalidTokenError()
    user = await UserRepo(session).get_by_id(user_id)
    if user is None:
        raise InvalidTokenError()
    return user
```

`app/routers/auth.py` 追加（import 补充 `User`、`get_current_user`、`RefreshRequest`、`TokenPair`、`UserOut`）：

```python
from app.db.models import User
from app.api.deps import get_current_user
from app.schemas.auth import RefreshRequest, TokenPair, UserOut


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest,
                  svc: AuthService = Depends(get_auth_service)) -> TokenPair:
    return await svc.refresh(req.refresh_token)


@router.post("/logout", status_code=204)
async def logout(req: RefreshRequest,
                 svc: AuthService = Depends(get_auth_service)) -> None:
    await svc.logout(req.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, phone=user.phone, created_at=user.created_at)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/integration -v && python -m pytest -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/api/deps.py app/routers/auth.py tests/integration/test_token_endpoints.py
git commit -m "feat: refresh/logout/me 端点与 Bearer 认证依赖"
```

---

### Task 11: docker-compose、.env.example、README 与端到端手动验证

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `README.md`
- Create: `.gitignore`
- Create: `app/db/init.py`（生产/开发启动时建表，供 uvicorn 启动脚本调用——开发用）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 可运行的本地开发环境：`docker compose up -d` 起 PG+Redis，`.env` 配置后 `uvicorn app.main:app --reload` 启动，Swagger UI 在 `/docs`

- [ ] **Step 1: 写 docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: superpower_demo
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

- [ ] **Step 2: 写 .env.example 与 .gitignore**

`.env.example`：

```
SMS_PROVIDER=mock
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/superpower_demo
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=change-me-to-a-random-string
ACCESS_TOKEN_TTL_MINUTES=30
REFRESH_TOKEN_TTL_DAYS=30
SMS_CODE_TTL_SECONDS=300
SMS_SEND_LIMIT_SECONDS=60
SMS_MAX_FAIL_COUNT=5
```

`.gitignore`：

```
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
```

- [ ] **Step 3: 写 app/db/init.py（启动建表，开发用）**

```python
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Base


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: 写 README.md**

包含：项目简介、启动步骤（venv → pip install → docker compose up -d → 复制 `.env.example` 为 `.env` 并改 `JWT_SECRET` → `uvicorn app.main:app --reload`）、Swagger 地址 `http://localhost:8000/docs`、五个端点的 curl 示例（发码后从控制台 `[MOCK SMS]` 输出中取验证码）、测试命令 `python -m pytest -v`。

curl 示例（写入 README 的实际内容）：

```bash
# 1. 发送验证码（控制台打印 [MOCK SMS] 13800000001 -> 123456）
curl -X POST http://localhost:8000/auth/send-code -H "Content-Type: application/json" -d '{"phone":"13800000001"}'

# 2. 验证登录
curl -X POST http://localhost:8000/auth/verify -H "Content-Type: application/json" -d '{"phone":"13800000001","code":"123456"}'

# 3. 刷新 token
curl -X POST http://localhost:8000/auth/refresh -H "Content-Type: application/json" -d '{"refresh_token":"<上一步返回的 refresh_token>"}'

# 4. 当前用户
curl http://localhost:8000/auth/me -H "Authorization: Bearer <access_token>"

# 5. 登出
curl -X POST http://localhost:8000/auth/logout -H "Content-Type: application/json" -d '{"refresh_token":"<refresh_token>"}'
```

- [ ] **Step 5: 全量测试确认无回归**

Run: `python -m pytest -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example .gitignore README.md app/db/init.py
git commit -m "chore: docker-compose、环境配置样例与运行文档"
```

---

## 收尾验证（全部任务完成后）

- [ ] `python -m pytest -v` 全绿
- [ ] `docker compose up -d` + `.env` + `uvicorn app.main:app --reload` 手动跑通 README 中的 5 个 curl（mock provider 控制台可见验证码）
- [ ] 浏览器打开 `/docs` 确认 OpenAPI 文档呈现五个端点
