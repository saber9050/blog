"""P0 基础设施自测。

覆盖四类：
1. 接口契约（health、统一响应、404）
2. 错误码映射
3. 安全组件（bcrypt / JWT / Fernet）
4. 模型定义（软删除过滤、表名）
"""

import pytest

from app.core.errors import BizError, ErrorCode, message_of
from app.core.response import ResponseBuilder
from app.core.security import CryptoBox, JWTManager, PasswordHasher
from app.core.timefmt import format_time_iso, format_time_z
from app.db.base import not_deleted
from app.db.models import ALL_MODELS, Article

# ============================================================
# 接口契约
# ============================================================


def test_health_returns_contract_shape(client):
    """健康检查必须返回 Go 版的原始结构，不能套统一响应。"""
    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "message": "core-coach API is running"}
    # 关键：不能有 code/data 字段
    assert "code" not in body
    assert "data" not in body


def test_unknown_route_returns_wrapped_404(client):
    """不存在的路由要返回统一响应结构，而不是 FastAPI 默认的 {"detail": ...}。"""
    resp = client.get("/api/v1/not-exists")

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 404
    assert body["message"] == "资源不存在"
    # 错误响应不应带 data 字段
    assert "data" not in body


def test_response_omits_none_data():
    """data 为 None 时字段整体缺省（对应 Go 的 omitempty）。"""
    resp = ResponseBuilder.ok(None)
    payload = resp.body.decode()

    assert '"data"' not in payload
    assert '"code":0' in payload


def test_response_keeps_falsy_data():
    """data 是 0 / [] / False 时不能当成 None 省略掉。"""
    import json

    for value in (0, [], False, ""):
        resp = ResponseBuilder.ok(value)
        payload = json.loads(resp.body)
        assert "data" in payload, f"{value!r} 被误判为 None"


def test_paginated_shape():
    """分页响应字段名固定为 page_size（下划线）。"""
    import json

    resp = ResponseBuilder.paginated(items=[], total=0, page=1, page_size=10)
    payload = json.loads(resp.body)["data"]

    assert set(payload) == {"list", "total", "page", "page_size"}


# ============================================================
# 错误码
# ============================================================


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (ErrorCode.BAD_REQUEST, 400),
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.INTERNAL_ERROR, 500),
        # 业务码统一映射 400
        (ErrorCode.USER_NOT_FOUND, 400),
        (ErrorCode.TOKEN_EXPIRED, 400),
        (ErrorCode.RESOURCE_LOCKED, 400),
    ],
)
def test_biz_error_http_status(code, expected_status):
    """业务码 → HTTP 状态码的映射规则。"""
    assert BizError(code).http_status == expected_status


def test_biz_error_default_message():
    """不传 message 时用错误码的默认文案。"""
    err = BizError(ErrorCode.USER_DISABLED)
    assert err.message == "用户已被禁用"
    assert message_of(ErrorCode.USER_DISABLED) == "用户已被禁用"


# ============================================================
# 安全组件
# ============================================================


def test_password_hash_and_verify():
    """bcrypt 哈希能校验，且同一密码每次哈希不同（盐随机）。"""
    hasher = PasswordHasher(rounds=4)  # 测试用低 cost，快
    plain = "abc12345678"

    h1 = hasher.hash(plain)
    h2 = hasher.hash(plain)

    assert h1 != h2
    assert h1.startswith("$2b$")
    assert hasher.verify(plain, h1)
    assert not hasher.verify("wrong-password", h1)


def test_password_rejects_oversize():
    """超过 72 字节的密码直接拒绝，而不是被 bcrypt 静默截断。"""
    hasher = PasswordHasher(rounds=4)
    with pytest.raises(ValueError, match="72"):
        hasher.hash("a" * 73)


def test_password_verify_tolerates_bad_hash():
    """哈希串是脏数据时返回 False，不抛异常。"""
    hasher = PasswordHasher(rounds=4)
    assert hasher.verify("whatever", "not-a-bcrypt-hash") is False


def test_jwt_roundtrip():
    """签发的 claims 能原样解析回来。"""
    manager = JWTManager(secret="test-secret-at-least-32-bytes-long!!", access_expire_minutes=15)
    token = manager.create_access_token(user_id=7, username="叶子", role_id=1, tid="abc123")

    claims = manager.decode(token)
    assert claims.user_id == 7
    assert claims.username == "叶子"
    assert claims.role_id == 1
    assert claims.tid == "abc123"


def test_jwt_expired_token_raises_code_1006():
    """过期 token 抛 1006，且「不校验过期」时仍能解出 claims。"""
    manager = JWTManager(
        secret="test-secret-at-least-32-bytes-long!!", access_expire_minutes=-1
    )  # 已过期
    token = manager.create_access_token(user_id=1, username="u", role_id=0, tid="t")

    with pytest.raises(BizError) as exc_info:
        manager.decode(token)
    assert exc_info.value.code == ErrorCode.TOKEN_EXPIRED

    # 刷新接口正是靠这个模式读过期 token 的 tid
    claims = manager.decode(token, verify_exp=False)
    assert claims.tid == "t"


def test_jwt_tampered_token_rejected():
    """改过签名的 token 抛 1005。"""
    manager = JWTManager(secret="test-secret-at-least-32-bytes-long!!")
    token = manager.create_access_token(user_id=1, username="u", role_id=0, tid="t")

    with pytest.raises(BizError) as exc_info:
        JWTManager(secret="another-secret-also-32-bytes-long!").decode(token)
    assert exc_info.value.code == ErrorCode.INVALID_TOKEN


def test_crypto_box_roundtrip():
    """Fernet 加解密可逆，且密文与明文不同。"""
    import base64

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    box = CryptoBox(key)

    assert box.is_secure
    cipher = box.encrypt("sk-1234567890")
    assert cipher != "sk-1234567890"
    assert box.decrypt(cipher) == "sk-1234567890"
    # 结果应是合法 base64，能存 VARCHAR
    base64.urlsafe_b64decode(cipher.encode())


def test_crypto_box_empty_key_passthrough():
    """FERNET_KEY 为空时明文透传，便于本地调试。"""
    box = CryptoBox("")
    assert not box.is_secure
    assert box.encrypt("plain") == "plain"
    assert box.decrypt("plain") == "plain"


# ============================================================
# 模型定义
# ============================================================


def test_all_models_registered():
    """10 张表全部注册，且表名与 Go 版一致（含 categorys 的拼写）。"""
    names = {m.__tablename__ for m in ALL_MODELS}

    assert names == {
        "users",
        "categorys",  # 少一个 e，是既有契约
        "tags",
        "tag_articles",
        "articles",
        "article_images",
        "comments",
        "likes",
        "abouts",
        "ai_model_configs",
    }


def test_article_has_no_vector_columns():
    """新库不建 4 个向量化列。"""
    columns = {c.name for c in Article.__table__.columns}

    for legacy in ("vector_status", "vector_chunk_count", "vector_error", "vectorized_at"):
        assert legacy not in columns, f"遗留列 {legacy} 不应存在"


def test_content_uses_mediumtext_on_mysql():
    """文章正文在 MySQL 下必须是 MEDIUMTEXT，否则长文会被静默截断。"""
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(Article.__table__).compile(dialect=mysql.dialect()))

    assert "MEDIUMTEXT" in ddl.upper()


def test_likes_has_unique_constraint():
    """点赞表必须有 (article_id, user_id) 唯一约束。"""
    constraint_names = {c.name for c in Article.__table__.metadata.tables["likes"].constraints}
    assert "uq_likes_article_id_user_id" in constraint_names


def test_not_deleted_filter_sql():
    """软删除过滤条件渲染成 `deleted_at IS NULL`。

    用 Article 而不是 Category：后者是物理删除，没有 `deleted_at` 列。
    """
    sql = str(not_deleted(Article).compile(compile_kwargs={"literal_binds": True}))
    assert "deleted_at IS NULL" in sql


# ============================================================
# 配置加载
# ============================================================


def test_config_yaml_is_parsed():
    """`configs/config.yaml` 必须能解析出预期结构。

    这条不校验具体值（你随时会改），只保证「文件存在、YAML 合法、分组齐全」。
    真值校验放在下面几条，用不依赖具体配置的方式测。
    """
    from pathlib import Path

    import yaml

    from app.core.config import CONFIG_FILE

    assert Path(CONFIG_FILE).exists(), f"缺少配置文件：{CONFIG_FILE}"
    data = yaml.safe_load(Path(CONFIG_FILE).read_text(encoding="utf-8"))

    for section in ("app", "database", "jwt", "minio", "smtp", "admin", "log"):
        assert section in data, f"配置缺少分组：{section}"

    # 嵌套分组也要在
    assert "mysql" in data["database"]
    assert "redis" in data["database"]


def test_yaml_values_reach_settings():
    """YAML 里的值必须原样进入 Settings。

    做法是「以 YAML 文件为基准比对」，而不是硬编码期望值 ——
    你随时可以改配置，这条测试不会因此失效。

    如果哪天 pydantic-settings 的 source 配置丢了（YAML 静默不生效），
    这里会立刻挂。
    """
    from pathlib import Path

    import yaml

    from app.core.config import CONFIG_FILE, Settings

    data = yaml.safe_load(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    settings = Settings()

    assert settings.app.mode == data["app"]["mode"]
    assert settings.app.port == data["app"]["port"]
    assert settings.database.mysql.pool_size == data["database"]["mysql"]["pool_size"]
    assert settings.database.redis.enabled == data["database"]["redis"]["enabled"]
    assert settings.business.max_page_size == data["business"]["max_page_size"]


def test_env_var_overrides_yaml(monkeypatch):
    """环境变量优先级高于 YAML（容器部署靠它注入密钥）。"""
    from app.core.config import Settings

    monkeypatch.setenv("APP__PORT", "9999")
    settings = Settings()

    assert settings.app.port == 9999


def test_init_kwargs_beat_env(monkeypatch):
    """显式传参优先级最高（测试里覆盖配置用）。"""
    from app.core.config import Settings

    monkeypatch.setenv("APP__MODE", "release")
    settings = Settings(app={"mode": "debug"})

    assert settings.app.mode == "debug"


# ============================================================
# 时间格式
# ============================================================


def test_time_format_z():
    """文章时间格式是「本地时间 + 字面 Z」。"""
    from datetime import datetime

    assert format_time_z(datetime(2026, 11, 10, 21, 39, 4)) == "2026-11-10T21:39:04Z"
    assert format_time_z(None) == ""


def test_time_format_iso_for_comment():
    """评论时间格式带 +08:00 偏移。"""
    from datetime import datetime

    assert format_time_iso(datetime(2026, 11, 10, 21, 39, 4)).startswith("2026-11-10T21:39:04")
    assert format_time_iso(datetime(2026, 11, 10, 21, 39, 4)).endswith("+08:00")
