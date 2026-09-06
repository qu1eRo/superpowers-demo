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
