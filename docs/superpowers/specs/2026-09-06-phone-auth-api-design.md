# 手机号验证登录 API 设计文档

日期：2026-09-06
状态：已确认

## 概述

基于手机号短信验证码的登录/注册一体化 API。用户提交手机号获取验证码，验证成功后自动完成登录；若手机号不存在则自动注册新用户。采用可插拔短信服务商接口，开发阶段使用 mock provider（验证码输出到控制台/日志）。

## 技术栈

- **框架**：Python + FastAPI，REST + OpenAPI（Swagger UI）
- **数据库**：PostgreSQL（用户数据，SQLAlchemy 异步）
- **缓存**：Redis（验证码、频率限制、refresh token）
- **认证**：JWT access token + opaque refresh token

## 架构

单体分层架构，依赖方向自上而下，每层只依赖下层的接口，测试时可任意替换。

```
routers      → 请求/响应校验、路由
services     → 业务逻辑（发码、验证、注册、签发 token）
repositories → 数据库访问（SQLAlchemy）
providers    → 短信发送（可插拔接口）
```

### 项目结构

```
superpower-demo/
├── app/
│   ├── main.py              # FastAPI 入口，挂载路由
│   ├── core/
│   │   ├── config.py        # Pydantic Settings（环境变量）
│   │   └── security.py      # JWT 创建/校验、refresh token 生成
│   ├── routers/
│   │   └── auth.py          # /auth/* 路由
│   ├── services/
│   │   └── auth_service.py  # 业务逻辑
│   ├── repositories/
│   │   └── user_repo.py     # 用户 CRUD
│   ├── providers/
│   │   ├── base.py          # SmsProvider 抽象接口
│   │   ├── mock.py          # 开发默认：控制台输出验证码
│   │   └── aliyun.py        # 阿里云 stub（接口预留）
│   ├── schemas/
│   │   └── auth.py          # Pydantic 请求/响应模型
│   └── db/
│       ├── models.py        # User ORM 模型
│       ├── session.py       # AsyncSession 工厂
│       └── redis.py         # Redis 连接
├── tests/                   # pytest + httpx AsyncClient
├── docker-compose.yml       # PostgreSQL + Redis（本地开发）
├── .env.example
└── pyproject.toml
```

## API 端点

| 端点 | 方法 | 请求 | 响应 | 说明 |
|---|---|---|---|---|
| `/auth/send-code` | POST | `{phone}` | `202 {expires_in}` | 发送验证码 |
| `/auth/verify` | POST | `{phone, code}` | `200 {access, refresh, user_id, is_new}` | 验证 + 自动注册 + 签发 token |
| `/auth/refresh` | POST | `{refresh}` | `200 {access, refresh}` | 轮换 refresh token |
| `/auth/logout` | POST | `{refresh}` | `204` | 吊销 refresh token |
| `/auth/me` | GET | Bearer token | `200 {user}` | 需认证 |

### 请求/响应模型

```python
# schemas/auth.py
class SendCodeRequest(BaseModel):
    phone: str  # 中国大陆手机号格式校验 ^1[3-9]\d{9}$

class VerifyRequest(BaseModel):
    phone: str
    code: str  # 6 位数字

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class VerifyResponse(TokenPair):
    user_id: int
    is_new: bool

class RefreshRequest(BaseModel):
    refresh_token: str

class UserOut(BaseModel):
    id: int
    phone: str
    created_at: datetime
```

## 数据模型

### PostgreSQL：users 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | 用户 ID |
| phone | VARCHAR(20) UNIQUE NOT NULL | 手机号（唯一） |
| created_at | TIMESTAMP DEFAULT now() | 注册时间 |
| updated_at | TIMESTAMP | 更新时间 |

### Redis 键设计

| 键 | 值 | TTL | 用途 |
|---|---|---|---|
| `sms:code:{phone}` | 6 位验证码 | 5 分钟 | 验证 |
| `sms:limit:{phone}` | 发送计数 | 60 秒 | 发送频率限制 |
| `sms:fail:{phone}` | 失败计数 | 5 分钟 | 连续失败锁定 |
| `refresh:{token}` | user_id | 30 天 | refresh token 存储 |

## 核心业务规则

### 发送验证码（/auth/send-code）

1. 校验手机号格式（Pydantic）
2. 检查 `sms:limit:{phone}` 是否存在 → 存在则 `429`
3. 生成 6 位随机数字验证码
4. 存入 `sms:code:{phone}`（TTL 5 分钟），设置 `sms:limit:{phone}`（TTL 60 秒）
5. 调用 SmsProvider 发送
6. 返回 `202 {expires_in: 300}`

### 验证登录（/auth/verify）

1. 检查 `sms:fail:{phone}` 是否达到 5 次 → 达到则 `429`（锁定）
2. 读取 `sms:code:{phone}` 比对
   - 不匹配：递增 `sms:fail:{phone}`，返回 `400`（不泄露剩余次数）
   - 匹配：删除验证码和失败计数
3. 按手机号查用户，不存在则创建（`is_new=true`）
4. 签发 access JWT（30 分钟，payload 含 `sub=user_id`、`exp`）
5. 生成随机 opaque refresh token，存 `refresh:{token}` → user_id（TTL 30 天）
6. 返回 `200`，包含 token 对和 `user_id`、`is_new`

### 刷新 token（/auth/refresh）

1. 校验 `refresh:{token}` 是否存在 → 不存在则 `401`
2. 吊销旧 refresh token（删除）
3. 签发新的 access + refresh token（轮换）
4. 返回 `200`

### 登出（/auth/logout）

1. 删除 `refresh:{token}` → 不存在也返回 `204`（幂等）

### /auth/me

1. 校验 Bearer access JWT → 无效/过期则 `401`
2. 返回当前用户信息

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SMS_PROVIDER` | `mock` | 短信服务商：`mock` / `aliyun` |
| `DATABASE_URL` | 本地 docker | PostgreSQL 连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `JWT_SECRET` | 无默认（必填） | JWT 签名密钥 |
| `ACCESS_TOKEN_TTL_MINUTES` | 30 | access token 有效期 |
| `REFRESH_TOKEN_TTL_DAYS` | 30 | refresh token 有效期 |
| `SMS_CODE_TTL_SECONDS` | 300 | 验证码有效期 |
| `SMS_SEND_LIMIT_SECONDS` | 60 | 发送间隔限制 |
| `SMS_MAX_FAIL_COUNT` | 5 | 验证失败锁定阈值 |

## 错误处理

统一错误响应格式：

```json
{"code": "ERROR_CODE", "message": "人类可读信息"}
```

| HTTP | code | 场景 |
|---|---|---|
| 400 | `INVALID_CODE` | 验证码错误或过期 |
| 401 | `INVALID_TOKEN` | token 无效/过期 |
| 422 | Pydantic 默认 | 请求格式错误（手机号格式不合法等） |
| 429 | `RATE_LIMITED` | 发送过于频繁 |
| 429 | `TOO_MANY_ATTEMPTS` | 验证失败次数过多被锁定 |
| 500 | `INTERNAL_ERROR` | 全局 exception handler 兜底，不泄漏堆栈 |

## 短信 Provider 接口

```python
# providers/base.py
class SmsProvider(ABC):
    @abstractmethod
    async def send_code(self, phone: str, code: str) -> None: ...
```

- `mock.py`：打印到控制台/日志（开发默认）
- `aliyun.py`：stub，方法签名就位，`NotImplementedError`，后续实现
- 由 `SMS_PROVIDER` 环境变量 + 依赖注入选择

## 测试策略

- **单元测试**（service 层）：mock repository + mock provider + fakeredis
  - 发码流程：频率限制、验证码生成与存储
  - 验证流程：正确/错误验证码、锁定逻辑、验证码一次性（验证后删除）
  - 自动注册：已存在/新用户
  - Token：刷新轮换（旧 refresh 失效）、登出吊销
- **集成测试**：httpx `AsyncClient` + 测试数据库 + fakeredis，覆盖完整 HTTP 流程
- TDD：先写测试再实现

## 非目标（YAGNI）

- 不做：密码登录、邮箱登录、图形验证码、用户资料管理、多因素认证、手机号换绑
- 不引入：Celery/消息队列、微服务拆分
- 阿里云 provider 仅留接口 stub，不实现真实调用
