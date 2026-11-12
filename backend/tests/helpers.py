"""测试公共工具。

认证与用户两个测试文件都要「造一个已登录用户」，把这套流程抽出来，
免得每个用例都写一遍取验证码 → 注册 → 登录。
"""

import asyncio
import secrets
import string

import redis as sync_redis
from fastapi.testclient import TestClient

API_AUTH = "/api/v1/auth"
API_USER = "/api/v1/user"
API_ADMIN = "/api/v1/admin/users"

TEST_PREFIX = "__t_"


def new_account() -> str:
    """生成 11 位不重复账号。"""
    return "1" + "".join(secrets.choice(string.digits) for _ in range(10))


def new_name() -> str:
    """生成带测试前缀的昵称（清理时按前缀删）。"""
    return TEST_PREFIX + "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))


def read_cache(client: TestClient, key: str) -> str | None:
    """同步读缓存。

    TestClient 自己占着事件循环，测试里不能 `asyncio.run` 调异步接口，
    所以按配置选一条同步路径。
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
    item = client.app.state.cache._store.get(key)  # noqa: SLF001 - 测试专用
    return item[0] if item else None


def exec_sql(client: TestClient, sql: str, params: dict) -> None:
    """直接执行写 SQL（构造测试前置状态用）。"""
    from sqlalchemy import text

    from app.db.database import Database

    db = Database(client.app.state.settings)

    async def _run() -> None:
        async with db.session_factory() as session:
            await session.execute(text(sql), params)
            await session.commit()
        await db.dispose()

    asyncio.run(_run())


def purge_test_users(client: TestClient) -> None:
    """删掉所有测试用户（按昵称前缀）。"""
    exec_sql(client, "DELETE FROM users WHERE user_name LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM users WHERE account LIKE :p", {"p": "19999%"})


def fetch_image_captcha(client: TestClient) -> tuple[str, str]:
    """取一组图形验证码，返回 (id, 答案)。"""
    resp = client.get(f"{API_AUTH}/image_captcha")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    captcha_id = data["captcha_id"]
    answer = read_cache(client, f"captcha:login:{captcha_id}")
    assert answer, "验证码没写进缓存"
    return captcha_id, answer


def register(
    client: TestClient,
    *,
    name: str | None = None,
    account: str | None = None,
    password: str = "abc12345678",
) -> tuple[str, str]:
    """注册一个测试用户，返回 (昵称, 账号)。"""
    name = name or new_name()
    account = account or new_account()
    resp = client.post(
        f"{API_AUTH}/register",
        json={"user_name": name, "account": account, "password": password, "ack": password},
    )
    assert resp.status_code == 200, resp.text
    return name, account


def login(
    client: TestClient,
    account: str,
    password: str = "abc12345678",
) -> dict:
    """账号密码登录，返回 data（含 access_token）。"""
    captcha_id, answer = fetch_image_captcha(client)
    resp = client.post(
        f"{API_AUTH}/login",
        json={
            "account": account,
            "password": password,
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def auth_headers(token: str) -> dict[str, str]:
    """拼 Authorization 头。"""
    return {"Authorization": f"Bearer {token}"}


def register_and_login(client: TestClient) -> tuple[str, str, str]:
    """注册 + 登录一步到位，返回 (昵称, 账号, access_token)。"""
    name, account = register(client)
    data = login(client, account)
    return name, account, data["access_token"]
