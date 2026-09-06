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
