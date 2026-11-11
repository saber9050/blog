"""认证模块测试。

策略：
- **走真实 HTTP + 真实 MySQL + 真实 Redis**，不 mock。
  认证是「数据库约束 + 缓存时序 + 密码哈希」三者耦合的地方，
  用 mock 测出来的绿色没有任何意义。
- 测试账号带随机后缀，跑完清理，不会污染库。
- 图形验证码的答案从缓存里读 —— 它不是给测试看的，而是模拟「用户看到图」。
"""

import secrets
import string

import pytest
import redis as sync_redis
from fastapi.testclient import TestClient

API = "/api/v1/auth"

# 测试数据的标记，清理时按它删
TEST_PREFIX = "__t_"


@pytest.fixture(scope="module")
def client(live_client):
    """复用 conftest 的 live_client（已禁用真实发信）。

    module 级：整个文件共用一次启动，避免每个用例都重连数据库。
    """
    return live_client


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清理测试账号。"""
    _purge_test_users(client)
    yield
    _purge_test_users(client)


def _purge_test_users(client: TestClient) -> None:
    """删除所有以测试前缀开头的用户。

    直接连库删，不走 API —— 没有「删用户」接口，也不该为测试加一个。
    """
    import asyncio

    from sqlalchemy import text

    from app.db.database import Database

    settings = client.app.state.settings
    db = Database(settings)

    async def _run() -> None:
        async with db.session_factory() as session:
            await session.execute(
                text("DELETE FROM users WHERE user_name LIKE :p"), {"p": f"{TEST_PREFIX}%"}
            )
            await session.commit()
        await db.dispose()

    asyncio.run(_run())


def _read_cache(client: TestClient, key: str) -> str | None:
    """同步读取缓存值。

    为什么不用 `app.state.cache`：它是异步接口，而 TestClient 自己占着一个事件循环，
    在测试函数里 `asyncio.run` 会和它打架。这里按配置选一条同步路径。
    """
    settings = client.app.state.settings
    if settings.database.redis.enabled:
        r = sync_redis.Redis(
            host=settings.database.redis.host,
            port=settings.database.redis.port,
            password=settings.database.redis.password.get_secret_value() or None,
            db=settings.database.redis.db,
            decode_responses=True,
        )
        return r.get(key)
    # 内存降级：内部就是个 dict，直接读
    item = client.app.state.cache._store.get(key)  # noqa: SLF001 - 测试专用
    return item[0] if item else None


def _new_account() -> str:
    """生成 11 位不重复账号。"""
    return "1" + "".join(secrets.choice(string.digits) for _ in range(10))


def _new_name() -> str:
    """生成带测试前缀的昵称。"""
    return TEST_PREFIX + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))


def _fetch_captcha(client: TestClient) -> tuple[str, str]:
    """取一组图形验证码，返回 (captcha_id, 答案)。

    答案从缓存读 —— 相当于「人眼看图」这一步。
    """
    resp = client.get(f"{API}/image_captcha")
    assert resp.status_code == 200
    data = resp.json()["data"]
    captcha_id = data["captcha_id"]
    answer = _read_cache(client, f"captcha:login:{captcha_id}")
    assert answer, "验证码没写进缓存"
    return captcha_id, answer


def _register(
    client: TestClient, *, name: str, account: str, password: str = "abc12345678"
) -> None:
    """注册一个测试用户。"""
    resp = client.post(
        f"{API}/register",
        json={"user_name": name, "account": account, "password": password, "ack": password},
    )
    assert resp.status_code == 200, resp.text


def _login(client: TestClient, account: str, password: str = "abc12345678") -> dict:
    """完整走一次账号密码登录，返回 data。"""
    captcha_id, answer = _fetch_captcha(client)
    resp = client.post(
        f"{API}/login",
        json={
            "account": account,
            "password": password,
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ============================================================
# 核心流程
# ============================================================


def test_full_auth_flow(client):
    """注册 → 登录 → 刷新 → 登出，一条链路走通。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    # 登录
    data = _login(client, account)
    assert data["user_name"] == name
    assert data["user_id"] > 0
    assert data["user_role_id"] == 0
    assert data["access_token"].count(".") == 2  # JWT 三段
    assert "refresh_token" not in data, "refresh token 绝不能下发"

    token = data["access_token"]

    # 刷新
    resp = client.post(f"{API}/refresh", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["data"]["access_token"]
    assert new_token != token, "刷新必须轮换 token"

    # 旧 token 因为 tid 已变，不能再刷新
    resp = client.post(f"{API}/refresh", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401

    # 登出（用新 token）
    resp = client.post(f"{API}/logout", headers={"Authorization": f"Bearer {new_token}"})
    assert resp.status_code == 200
    assert "data" not in resp.json(), "登出响应不该带 data 字段"

    # 登出后 refresh 失效
    resp = client.post(f"{API}/refresh", headers={"Authorization": f"Bearer {new_token}"})
    assert resp.status_code == 401


def test_register_rejects_bad_input(client):
    """注册的四类参数错误，各自返回对应文案。"""
    cases = [
        # 账号 10 位
        (
            {"user_name": _new_name(), "account": "1234567890", "password": "abc12345678"},
            "账号格式错误",
        ),
        # 密码纯数字
        (
            {"user_name": _new_name(), "account": _new_account(), "password": "12345678901"},
            "密码格式错误",
        ),
        # 密码纯字母
        (
            {"user_name": _new_name(), "account": _new_account(), "password": "abcdefghijk"},
            "密码格式错误",
        ),
        # 密码 10 位（差一位）
        (
            {"user_name": _new_name(), "account": _new_account(), "password": "abc1234567"},
            "密码格式错误",
        ),
    ]
    for payload, expected in cases:
        resp = client.post(f"{API}/register", json={**payload, "ack": payload["password"]})
        assert resp.status_code == 400, f"{payload} 应返回 400"
        assert resp.json()["message"] == expected


def test_register_rejects_mismatched_ack(client):
    """两次密码不一致。"""
    resp = client.post(
        f"{API}/register",
        json={
            "user_name": _new_name(),
            "account": _new_account(),
            "password": "abc12345678",
            "ack": "abc12345679",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "两次密码不一致"


def test_register_rejects_duplicate_name(client):
    """昵称重复 → 409。大小写不同也算重复（MySQL ci 排序规则）。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    resp = client.post(
        f"{API}/register",
        json={
            "user_name": name.upper(),
            "account": _new_account(),
            "password": "abc12345678",
            "ack": "abc12345678",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == "该昵称已经存在"


def test_register_rejects_duplicate_account(client):
    """账号重复 → 409。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    resp = client.post(
        f"{API}/register",
        json={
            "user_name": _new_name(),
            "account": account,
            "password": "abc12345678",
            "ack": "abc12345678",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == "该账号已经存在"


# ============================================================
# 验证码
# ============================================================


def test_image_captcha_shape(client):
    """图形验证码返回 captcha_id + data URI，字段名是 base_64。"""
    resp = client.get(f"{API}/image_captcha")
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert set(data) == {"captcha_id", "base_64"}
    assert data["base_64"].startswith("data:image/png;base64,")
    # 6 位数字答案存在缓存里
    answer = _read_cache(client, f"captcha:login:{data['captcha_id']}")
    assert answer and len(answer) == 6 and answer.isdigit()


def test_captcha_is_one_time(client):
    """同一个验证码用第二次 → 「验证码已过期」（用完即删）。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    captcha_id, answer = _fetch_captcha(client)
    payload = {
        "account": account,
        "password": "abc12345678",
        "captcha_key": captcha_id,
        "captcha_code": answer,
    }

    assert client.post(f"{API}/login", json=payload).status_code == 200

    resp = client.post(f"{API}/login", json=payload)
    assert resp.status_code == 400
    assert resp.json()["message"] == "验证码已过期"


def test_wrong_captcha_also_consumes_key(client):
    """验证码输错也会删 key，防止 300 秒内爆破同一个 key。"""
    captcha_id, answer = _fetch_captcha(client)
    wrong = "000000" if answer != "000000" else "111111"

    resp = client.post(
        f"{API}/login",
        json={
            "account": _new_account(),
            "password": "abc12345678",
            "captcha_key": captcha_id,
            "captcha_code": wrong,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "验证码错误"

    # key 已被删
    assert _read_cache(client, f"captcha:login:{captcha_id}") is None


def test_login_rejects_unknown_account(client):
    """账号不存在 → 404。"""
    captcha_id, answer = _fetch_captcha(client)
    resp = client.post(
        f"{API}/login",
        json={
            "account": _new_account(),
            "password": "abc12345678",
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "该账号不存在"


def test_login_rejects_wrong_password(client):
    """密码错误 → 400。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    captcha_id, answer = _fetch_captcha(client)
    resp = client.post(
        f"{API}/login",
        json={
            "account": account,
            "password": "wrong1234567",
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "密码错误"


# ============================================================
# 登出幂等 / 唯一性检测
# ============================================================


@pytest.mark.parametrize(
    ("headers", "label"),
    [
        ({}, "不带 Authorization"),
        ({"Authorization": "NotBearer xxx"}, "前缀不是 Bearer"),
        ({"Authorization": "Bearer not-a-jwt-at-all"}, "内容不是 JWT"),
    ],
)
def test_logout_is_idempotent(client, headers, label):
    """登出永远成功，token 有没有效都一样。"""
    resp = client.post(f"{API}/logout", headers=headers)
    assert resp.status_code == 200, f"{label} 也应当成功"


def test_exists_endpoints(client):
    """昵称 / 账号唯一性检测。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    # 已存在
    resp = client.get(f"{API}/is_exists_name", params={"user_name": name})
    assert resp.json()["data"]["is_exists"] is True

    resp = client.get(f"{API}/is_exists_account", params={"account": account})
    assert resp.json()["data"]["is_exists"] is True

    # 不存在
    resp = client.get(f"{API}/is_exists_name", params={"user_name": _new_name()})
    assert resp.json()["data"]["is_exists"] is False


def test_login_after_logout_works(client):
    """登出后再登录能拿到新会话（验证 refresh key 被删干净）。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    first = _login(client, account)
    client.post(f"{API}/logout", headers={"Authorization": f"Bearer {first['access_token']}"})

    second = _login(client, account)
    assert second["access_token"] != first["access_token"]


# ============================================================
# 禁用账号
# ============================================================


def _exec_sql(client: TestClient, sql: str, params: dict) -> None:
    """直接执行一条写 SQL（用于构造测试前置状态）。"""
    import asyncio

    from sqlalchemy import text

    from app.db.database import Database

    db = Database(client.app.state.settings)

    async def _run() -> None:
        async with db.session_factory() as session:
            await session.execute(text(sql), params)
            await session.commit()
        await db.dispose()

    asyncio.run(_run())


def test_disabled_user_cannot_login(client):
    """禁用账号登录返回 code=1004（不是 403，前端按 code 判断）。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)
    _exec_sql(client, "UPDATE users SET status = 0 WHERE account = :a", {"a": account})

    captcha_id, answer = _fetch_captcha(client)
    resp = client.post(
        f"{API}/login",
        json={
            "account": account,
            "password": "abc12345678",
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    # 1004 属于业务码，HTTP 状态映射为 400
    assert resp.status_code == 400
    assert resp.json()["code"] == 1004
    assert resp.json()["message"] == "用户已被禁用"


# ============================================================
# 邮箱验证码
# ============================================================


def test_email_captcha_send_and_login(client):
    """发验证码 → 从缓存取码 → 邮箱登录。

    本地没配 SMTP，`EmailSender` 在 debug 模式下降级为「只打日志不发信」，
    所以这条用例能验证完整流程而不需要真实邮箱。
    """
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    email = f"{secrets.token_hex(4)}@example.com"
    _exec_sql(client, "UPDATE users SET email = :e WHERE account = :a", {"e": email, "a": account})

    # 发验证码
    resp = client.post(f"{API}/captcha", json={"email": email, "purpose": "login"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["message"] == "已向你的邮箱发送验证码"

    code = _read_cache(client, f"captcha:email:{email}:login")
    assert code and len(code) == 6

    # 用错误验证码登录
    resp = client.post(
        f"{API}/email_login",
        json={
            "email": email,
            "purpose": "login",
            "captcha": "000000" if code != "000000" else "111111",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "验证码错误"

    # 用正确验证码登录
    resp = client.post(
        f"{API}/email_login",
        json={"email": email, "purpose": "login", "captcha": code},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user_name"] == name

    # 用过的验证码已删除
    assert _read_cache(client, f"captcha:email:{email}:login") is None


def test_email_captcha_rate_limit(client):
    """60 秒内连发两次 → 第二次 400。"""
    email = f"{secrets.token_hex(4)}@example.com"

    resp = client.post(f"{API}/captcha", json={"email": email, "purpose": "login"})
    assert resp.status_code == 200

    resp = client.post(f"{API}/captcha", json={"email": email, "purpose": "login"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "请勿频繁发送验证码，请60秒后再试"


def test_email_captcha_limit_is_cross_purpose(client):
    """频率限制只按邮箱算，换 purpose 也不能绕过。"""
    email = f"{secrets.token_hex(4)}@example.com"

    assert (
        client.post(f"{API}/captcha", json={"email": email, "purpose": "login"}).status_code == 200
    )

    resp = client.post(f"{API}/captcha", json={"email": email, "purpose": "reset_password"})
    assert resp.status_code == 400
    assert "频繁" in resp.json()["message"]


def test_email_login_rejects_unknown_email(client):
    """未注册的邮箱 → 404。"""
    resp = client.post(
        f"{API}/email_login",
        json={"email": "nobody@example.com", "purpose": "login", "captcha": "123456"},
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "该邮箱未注册"


# ============================================================
# 重置密码
# ============================================================


def test_reset_password_flow(client):
    """发重置验证码 → 改密 → 用新密码登录。"""
    name, account = _new_name(), _new_account()
    _register(client, name=name, account=account)

    email = f"{secrets.token_hex(4)}@example.com"
    _exec_sql(client, "UPDATE users SET email = :e WHERE account = :a", {"e": email, "a": account})

    assert (
        client.post(
            f"{API}/captcha", json={"email": email, "purpose": "reset_password"}
        ).status_code
        == 200
    )
    code = _read_cache(client, f"captcha:email:{email}:reset_password")
    assert code

    new_password = "newpass12345"
    resp = client.post(
        f"{API}/reset_password",
        json={"email": email, "captcha": code, "new_password": new_password, "ack": new_password},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["message"] == "成功修改密码"

    # 旧密码登录失败
    captcha_id, answer = _fetch_captcha(client)
    resp = client.post(
        f"{API}/login",
        json={
            "account": account,
            "password": "abc12345678",
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "密码错误"

    # 新密码能登录
    data = _login(client, account, password=new_password)
    assert data["user_id"] > 0
