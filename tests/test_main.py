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
