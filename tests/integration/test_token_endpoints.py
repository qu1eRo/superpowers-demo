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
