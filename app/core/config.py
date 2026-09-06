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
