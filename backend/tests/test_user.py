"""用户模块测试。

覆盖前台 8 条 + 后台 4 条。全部走真实 MySQL / Redis / MinIO。

头像相关的用例会在 MinIO 不可达时自动跳过（而不是失败）——
本地偶尔没起对象存储是常态，不该让整个测试套件红掉。
"""

import io
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from tests.helpers import (
    API_ADMIN,
    API_AUTH,
    API_USER,
    auth_headers,
    exec_sql,
    login,
    new_account,
    new_name,
    purge_test_users,
    read_cache,
    register,
    register_and_login,
)


@pytest.fixture(scope="module")
def client(live_client):
    """复用 conftest 的 live_client（已禁用真实发信）。"""
    return live_client


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清理。"""
    purge_test_users(client)
    yield
    purge_test_users(client)


@pytest.fixture(scope="module")
def minio_available(client) -> bool:
    """MinIO 是否可用。不可用时跳过头像用例。"""
    import asyncio

    return asyncio.run(client.app.state.storage.ensure_bucket())


def _tiny_png() -> bytes:
    """手搓一张 1x1 的 PNG，避免测试依赖图片文件。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    # 1x1 真彩色图像：每行前有一个 filter 字节 0
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


# ============================================================
# 我的资料
# ============================================================


def test_get_info_contract(client):
    """资料接口的字段名必须是 `staus` / `create_at`（历史拼写）。"""
    name, account, token = register_and_login(client)

    resp = client.get(f"{API_USER}/info", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert set(data) == {
        "user_id",
        "user_name",
        "account",
        "email",
        "avatar_url",
        "introduction",
        "role_id",
        "staus",  # 拼错的，不能改
        "create_at",  # 拼错的，不能改
    }
    assert data["user_name"] == name
    assert data["account"] == account
    assert data["email"] == ""
    assert data["avatar_url"] == ""
    assert data["introduction"] == ""
    assert data["staus"] == 1
    assert data["role_id"] == 0
    assert data["create_at"].endswith("Z")


def test_get_info_requires_auth(client):
    """未登录 → 401。"""
    resp = client.get(f"{API_USER}/info")
    assert resp.status_code == 401


# ============================================================
# 编辑资料
# ============================================================


def test_update_profile_changes_fields(client):
    """改昵称与简介。"""
    _, _, token = register_and_login(client)
    new_nick = new_name()

    resp = client.post(
        f"{API_USER}/profile",
        json={"nick_name": new_nick, "introduction": "写 Go 和 Python"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    data = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert data["user_name"] == new_nick
    assert data["introduction"] == "写 Go 和 Python"


def test_update_profile_same_name_is_allowed(client):
    """昵称原样提交不算重复（查重必须排除自己）。"""
    name, _, token = register_and_login(client)

    resp = client.post(
        f"{API_USER}/profile",
        json={"nick_name": name, "introduction": "只改简介"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_update_profile_rejects_taken_name(client):
    """昵称被别人占用 → 409。"""
    name_a, _, token_a = register_and_login(client)
    name_b, _, _ = register_and_login(client)

    resp = client.post(
        f"{API_USER}/profile",
        json={"nick_name": name_b},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == "该昵称已经存在"


def test_update_profile_can_clear_introduction(client):
    """传 `""` 能清空简介（Go 版清不掉，本轮修掉）。"""
    _, _, token = register_and_login(client)

    client.post(
        f"{API_USER}/profile",
        json={"introduction": "先写点东西"},
        headers=auth_headers(token),
    )
    data = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert data["introduction"] == "先写点东西"

    resp = client.post(
        f"{API_USER}/profile", json={"introduction": ""}, headers=auth_headers(token)
    )
    assert resp.status_code == 200

    data = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert data["introduction"] == "", "传空字符串应当清空简介"


def test_update_profile_omitted_field_untouched(client):
    """只传昵称时简介不应被清空。"""
    _, _, token = register_and_login(client)
    client.post(
        f"{API_USER}/profile",
        json={"introduction": "保留我"},
        headers=auth_headers(token),
    )

    client.post(f"{API_USER}/profile", json={"nick_name": new_name()}, headers=auth_headers(token))

    data = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert data["introduction"] == "保留我"


# ============================================================
# 头像
# ============================================================


def test_avatar_rejects_bad_extension(client):
    """非图片扩展名 → 400。"""
    _, _, token = register_and_login(client)

    resp = client.post(
        f"{API_USER}/avatar",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "不支持的文件格式"


def test_avatar_rejects_oversize(client, minio_available):
    """超过 10 MB → 400。"""
    if not minio_available:
        pytest.skip("MinIO 不可用")

    _, _, token = register_and_login(client)
    big = b"\x00" * (10 * 1024 * 1024 + 1)

    resp = client.post(
        f"{API_USER}/avatar",
        files={"file": ("big.png", big, "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "图片大小不能超过 10MB"


def test_avatar_upload_and_replace(client, minio_available):
    """上传头像 → 返回完整 URL → 资料接口能读到 → 再传一次旧图被清理。"""
    if not minio_available:
        pytest.skip("MinIO 不可用")

    _, _, token = register_and_login(client)
    png = _tiny_png()

    resp = client.post(
        f"{API_USER}/avatar",
        files={"file": ("a.png", io.BytesIO(png), "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    first_url = resp.json()["data"]["avatar_url"]
    assert first_url.startswith("http")
    assert "all/" in first_url

    info = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert info["avatar_url"] == first_url

    # 再传一次，URL 应变化
    resp = client.post(
        f"{API_USER}/avatar",
        files={"file": ("b.png", io.BytesIO(png), "image/png")},
        headers=auth_headers(token),
    )
    second_url = resp.json()["data"]["avatar_url"]
    assert second_url != first_url


# ============================================================
# 修改密码
# ============================================================


def test_update_password_flow(client):
    """旧密码错 → 400；成功后可换新密码登录。"""
    _, account, token = register_and_login(client)

    resp = client.post(
        f"{API_USER}/password",
        json={
            "old_password": "wrong1234567",
            "new_password": "newpass12345",
            "ack": "newpass12345",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "密码错误"

    resp = client.post(
        f"{API_USER}/password",
        json={"old_password": "abc12345678", "new_password": "newpass12345", "ack": "newpass12345"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    data = login(client, account, password="newpass12345")
    assert data["user_id"] > 0


def test_update_password_rejects_bad_format(client):
    """新密码不满足规则 → 400。"""
    _, _, token = register_and_login(client)

    resp = client.post(
        f"{API_USER}/password",
        json={"old_password": "abc12345678", "new_password": "12345678901", "ack": "12345678901"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "密码格式错误"


def test_update_password_rejects_mismatch(client):
    """两次不一致 → 400。"""
    _, _, token = register_and_login(client)

    resp = client.post(
        f"{API_USER}/password",
        json={"old_password": "abc12345678", "new_password": "newpass12345", "ack": "newpass12346"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "两次密码不一致"


# ============================================================
# 邮箱
# ============================================================


def _bind_email(client: TestClient, account: str, email: str) -> None:
    """直接写库绑定邮箱（没有绑定接口，只能这样造数据）。"""
    exec_sql(client, "UPDATE users SET email = :e WHERE account = :a", {"e": email, "a": account})


def _send_captcha(client: TestClient, email: str, purpose: str) -> str:
    """发验证码并从缓存读出来。"""
    resp = client.post(f"{API_AUTH}/captcha", json={"email": email, "purpose": purpose})
    assert resp.status_code == 200, resp.text
    code = read_cache(client, f"captcha:email:{email}:{purpose}")
    assert code
    return code


def test_is_exists_email(client):
    """邮箱唯一性检测，参数名是 new_email。"""
    _, account, token = register_and_login(client)
    email = f"{new_name()}@example.com"
    _bind_email(client, account, email)

    resp = client.get(
        f"{API_USER}/is_exists_email", params={"new_email": email}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_exists"] is True

    resp = client.get(
        f"{API_USER}/is_exists_email",
        params={"new_email": "nobody@example.com"},
        headers=auth_headers(token),
    )
    assert resp.json()["data"]["is_exists"] is False


def test_add_email_rejects_when_exists(client):
    """已有邮箱时补绑 → 403（不是 400）。"""
    _, account, token = register_and_login(client)
    _bind_email(client, account, f"{new_name()}@example.com")

    resp = client.post(
        f"{API_USER}/add_email",
        json={"new_email": f"{new_name()}@example.com", "captcha": "123456"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == "用户已存在邮箱，不可再添加"


def test_add_email_success(client):
    """没绑过邮箱时补绑成功。"""
    _, _, token = register_and_login(client)
    email = f"{new_name()}@example.com"
    code = _send_captcha(client, email, "add_email")

    resp = client.post(
        f"{API_USER}/add_email",
        json={"new_email": email, "captcha": code},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["message"] == "添加成功"

    data = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert data["email"] == email


def test_email_change_two_step_flow(client):
    """换绑邮箱：申请 → 用 token 打开链接 → 邮箱真的变了 → 再点一次失败。"""
    _, account, token = register_and_login(client)
    old_email = f"{new_name()}@example.com"
    new_email = f"{new_name()}@example.com"
    _bind_email(client, account, old_email)

    # 第一步：申请（验证码发到当前邮箱）
    code = _send_captcha(client, old_email, "reset_email")
    resp = client.post(
        f"{API_USER}/email_ack",
        json={"password": "abc12345678", "captcha": code, "new_email": new_email},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["message"] == "已发送确认邮件到新邮箱，请到邮箱确认"

    # 邮箱此时还没变
    info = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert info["email"] == old_email

    # 邮件里的链接：从 Redis 拿不到 token（它是邮件正文里），
    # 测试里直接重新签发一个等价 token
    from app.core.security import JWTManager

    jwt_manager: JWTManager = client.app.state.jwt
    confirm_token = jwt_manager.create_purpose_token(
        {"user_id": info["user_id"], "username": new_email}, expire_seconds=300
    )

    resp = client.get(f"{API_USER}/email", params={"token": confirm_token})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "邮箱修改成功" in resp.text

    info = client.get(f"{API_USER}/info", headers=auth_headers(token)).json()["data"]
    assert info["email"] == new_email

    # 第二次点同一个链接 → 页面显示失败（HTTP 仍是 200）
    resp = client.get(f"{API_USER}/email", params={"token": confirm_token})
    assert resp.status_code == 200
    assert "邮箱修改失败" in resp.text


def test_confirm_email_without_token(client):
    """不带 token 打开链接 → 失败页，HTTP 200。"""
    resp = client.get(f"{API_USER}/email")
    assert resp.status_code == 200
    assert "邮箱修改失败" in resp.text
    assert "缺少必要的确认信息" in resp.text


def test_confirm_email_with_bad_token(client):
    """token 无效 → 失败页，HTTP 200。"""
    resp = client.get(f"{API_USER}/email", params={"token": "not-a-valid-jwt"})
    assert resp.status_code == 200
    assert "邮箱修改失败" in resp.text


def test_email_change_rejects_wrong_password(client):
    """申请换绑时密码错误 → 400。"""
    _, account, token = register_and_login(client)
    old_email = f"{new_name()}@example.com"
    _bind_email(client, account, old_email)
    code = _send_captcha(client, old_email, "reset_email")

    resp = client.post(
        f"{API_USER}/email_ack",
        json={"password": "wrong1234567", "captcha": code, "new_email": "x@example.com"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "密码错误"


# ============================================================
# 后台
# ============================================================


def _admin_headers(client: TestClient) -> dict[str, str]:
    """登录默认管理员，返回 Authorization 头。"""
    settings = client.app.state.settings
    data = login(client, settings.admin.account, settings.admin.password.get_secret_value())
    return auth_headers(data["access_token"])


def test_admin_endpoints_require_admin(client):
    """普通用户访问后台 → 403。"""
    _, _, token = register_and_login(client)

    resp = client.get(API_ADMIN, headers=auth_headers(token))
    assert resp.status_code == 403

    resp = client.get(API_ADMIN)  # 未登录
    assert resp.status_code == 401


def test_admin_list_excludes_admins(client):
    """列表只返回普通用户，管理员不在里面。"""
    headers = _admin_headers(client)
    name, account = register(client)

    resp = client.get(API_ADMIN, params={"keyword": name}, headers=headers)
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["list"], "应当能搜到刚注册的用户"
    assert all(item["user_name"] != "管理员" for item in data["list"])
    # 分页字段是驼峰
    assert "pageSize" in data
    assert "page_size" not in data


def test_admin_create_user(client):
    """后台创建用户。"""
    headers = _admin_headers(client)
    name, account = new_name(), new_account()

    resp = client.post(
        API_ADMIN,
        json={"user_name": name, "account": account, "password": "test1234567", "status": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["data"]["id"]
    assert new_id > 0

    # 能登录
    data = login(client, account, password="test1234567")
    assert data["user_id"] == new_id


def test_admin_create_user_rejects_duplicate(client):
    """重复昵称 → 409。"""
    headers = _admin_headers(client)
    name, _ = register(client)

    resp = client.post(
        API_ADMIN,
        json={
            "user_name": name,
            "account": new_account(),
            "password": "test1234567",
            "status": 1,
        },
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == "该昵称已经存在"


def test_admin_cannot_modify_self(client):
    """管理员不能禁用/删除自己。"""
    headers = _admin_headers(client)
    settings = client.app.state.settings
    me = login(client, settings.admin.account, settings.admin.password.get_secret_value())

    resp = client.put(f"{API_ADMIN}/{me['user_id']}", json={"status": 0}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["message"] == "不能修改自己的状态"

    resp = client.delete(f"{API_ADMIN}/{me['user_id']}", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["message"] == "不能删除自己"


def test_admin_disable_and_delete(client):
    """禁用 → 该用户登录被 1004 拦；删除后列表里消失。"""
    headers = _admin_headers(client)
    name, account = register(client)
    user_id = login(client, account)["user_id"]

    # 禁用
    resp = client.put(f"{API_ADMIN}/{user_id}", json={"status": 0}, headers=headers)
    assert resp.status_code == 200, resp.text

    captcha_id, answer = (
        client.get(f"{API_AUTH}/image_captcha").json()["data"]["captcha_id"],
        None,
    )
    answer = read_cache(client, f"captcha:login:{captcha_id}")
    resp = client.post(
        f"{API_AUTH}/login",
        json={
            "account": account,
            "password": "abc12345678",
            "captcha_key": captcha_id,
            "captcha_code": answer,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1004

    # 删除
    resp = client.delete(f"{API_ADMIN}/{user_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.get(API_ADMIN, params={"keyword": name}, headers=headers)
    assert resp.json()["data"]["total"] == 0


def test_admin_delete_unknown_user(client):
    """删除不存在的用户 → 404。"""
    headers = _admin_headers(client)
    resp = client.delete(f"{API_ADMIN}/99999999", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["message"] == "用户不存在"
