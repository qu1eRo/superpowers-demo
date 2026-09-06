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
