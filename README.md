# Phone Auth API

手机号验证码登录 API demo——基于 FastAPI + PostgreSQL + Redis 实现「发送验证码 → 验证登录 → 刷新 / 登出 / 当前用户」的完整认证流程。

- **POST /auth/send-code**：向手机号发送验证码（202）
- **POST /auth/verify**：校验验证码，未注册用户自动注册，签发 access / refresh token
- **POST /auth/refresh**：用 refresh token 换取新的 token 对
- **POST /auth/logout**：吊销 refresh token（204）
- **GET /auth/me**：获取当前登录用户信息

短信通道为可插拔 Provider（`SMS_PROVIDER=mock` 时验证码打印 `[MOCK SMS] {phone} -> {code}` 到控制台）。

## 技术栈

Python >= 3.11 · FastAPI · SQLAlchemy 2.0 (asyncio, asyncpg) · Redis · PyJWT · pydantic-settings

## 快速开始

### 1. 创建虚拟环境并安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -e ".[dev]"
```

### 2. 启动 PostgreSQL 与 Redis

```bash
docker compose up -d
```

（PG16 暴露在 `localhost:5432`，Redis7 暴露在 `localhost:6379`。）

### 3. 准备 `.env` 并修改 `JWT_SECRET`

```bash
cp .env.example .env
# Windows (PowerShell): Copy-Item .env.example .env
```

编辑 `.env`，把 `JWT_SECRET` 改为一个随机字符串。

### 4. 建表（首次启动前执行一次）

```bash
python -c "import asyncio, os; from sqlalchemy.ext.asyncio import create_async_engine; from app.db.init import create_tables; asyncio.run(create_tables(create_async_engine(os.environ['DATABASE_URL'])))"
```

该命令读取环境变量 `DATABASE_URL` 建表。由于 Windows 的 `set` / PowerShell 的 `$env:` 只对当前会话生效，最简单的做法是把 `DATABASE_URL` 写进 `.env` 再配合 Python 读取（`.env` 不会被 pydantic 自动加载到 `os.environ`），可用下面的一行版本：

```bash
python -c "import asyncio; from pydantic_settings import BaseSettings; from sqlalchemy.ext.asyncio import create_async_engine; from app.db.init import create_tables; from app.core.config import Settings; s = Settings(); asyncio.run(create_tables(create_async_engine(s.database_url)))"
```

（第二种写法直接复用应用的 `Settings`，从 `.env` 读取 `DATABASE_URL`，无需手动导出环境变量。）

### 5. 启动服务

```bash
uvicorn app.main:app --reload
```

Swagger UI：<http://localhost:8000/docs>

## curl 示例

发码后从控制台 `[MOCK SMS]` 输出中取验证码（curl 示例中的 `123456` 为示意值，实际验证码以控制台输出为准）。

```bash
# 1. 发送验证码（控制台打印 [MOCK SMS] 13800000001 -> <code>，<code> 为实际验证码，下同）
curl -X POST http://localhost:8000/auth/send-code -H "Content-Type: application/json" -d '{"phone":"13800000001"}'

# 2. 验证登录（<code> 替换为控制台打印的实际验证码）
curl -X POST http://localhost:8000/auth/verify -H "Content-Type: application/json" -d '{"phone":"13800000001","code":"123456"}'

# 3. 刷新 token
curl -X POST http://localhost:8000/auth/refresh -H "Content-Type: application/json" -d '{"refresh_token":"<上一步返回的 refresh_token>"}'

# 4. 当前用户
curl http://localhost:8000/auth/me -H "Authorization: Bearer <access_token>"

# 5. 登出
curl -X POST http://localhost:8000/auth/logout -H "Content-Type: application/json" -d '{"refresh_token":"<refresh_token>"}'
```

## 运行测试

```bash
python -m pytest -v
```

## 项目结构

```
app/
  api/            # 依赖注入
  core/           # 配置、错误、JWT
  db/             # 模型、会话工厂、init（建表）、redis
  providers/      # 可插拔短信 Provider（mock 实现）
  repositories/   # UserRepo
  routers/        # /auth 路由
  schemas/        # 请求 / 响应模型
  services/       # 认证业务逻辑
tests/
```
