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

### 4. 启动服务

```bash
uvicorn app.main:app --reload
```

启动时建表（开发用）可调用 `app.db.init.create_tables`。Swagger UI：<http://localhost:8000/docs>

## curl 示例

发码后从控制台 `[MOCK SMS]` 输出中取验证码。

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
