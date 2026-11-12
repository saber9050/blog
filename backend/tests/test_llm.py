"""AI 模型模块测试。

两类：

1. **纯函数**：脱敏、正文清洗、摘要清洗 —— 直接调，不走 HTTP
2. **接口**：配置 CRUD 与摘要生成 —— 用 monkeypatch 把 `LLMClient` 的两个方法
   换成假实现。真调上游会花钱而且不稳定（网络抖一下就红），
   测试要能确定性通过。

被测的关键行为：
- 新建配置**先测连接，失败不入库**
- 更新只改运行参数，`base_url` / `api_key` / `model` 不受影响
- `api_key` 响应里只有脱敏串，且规则是「前 3 + **** + 后 4」
- 摘要不落库、去引号、截断到 255
"""

import pytest

from app.integrations.llm_client import LLMClient
from app.services.llm_service import LLMService
from tests.helpers import auth_headers, login

API = "/api/v1"


@pytest.fixture(scope="module")
def client(live_client):
    """复用 conftest 的 live_client。"""
    return live_client


@pytest.fixture(scope="function")
def fake_llm(monkeypatch):
    """把 LLMClient 的两个方法换成假实现。

    返回一个可调的「剧本」：改 `state` 就能控制下一次调用的成败。
    """
    state = {"ok": True, "reply": "连接成功", "error": None, "summary": "这是一段摘要。"}

    async def fake_test(self, *, base_url, api_key, model, timeout_sec=15):
        if state["ok"]:
            return True, 42, state["reply"], None
        return False, 42, None, state["error"]

    async def fake_chat(self, **kwargs):
        if not state["ok"]:
            from app.core.errors import BizError, ErrorCode

            raise BizError(ErrorCode.INTERNAL_ERROR, state["error"] or "调用失败")
        return state["summary"]

    monkeypatch.setattr(LLMClient, "test_connection", fake_test)
    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    return state


def _admin_headers(client) -> dict[str, str]:
    """登录管理员。"""
    settings = client.app.state.settings
    data = login(client, settings.admin.account, settings.admin.password.get_secret_value())
    return auth_headers(data["access_token"])


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清空模型配置。"""
    from tests.helpers import exec_sql

    exec_sql(client, "DELETE FROM ai_model_configs", {})
    yield
    exec_sql(client, "DELETE FROM ai_model_configs", {})


# ============================================================
# 纯函数
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("abc", "****"),
        ("abcd", "****"),
        ("abcde", "abc****bcde"),
        ("sk-1234567890abcdef", "sk-****cdef"),
    ],
)
def test_mask_key(raw, expected):
    """脱敏规则：前 3 + **** + 后 4，长度 ≤ 4 全遮。"""
    assert LLMService.mask_key(raw) == expected


def test_strip_markup_removes_tags_and_images():
    """正文清洗：去 HTML 标签与图片标记，保留链接文字。"""
    content = """
    <h1>标题</h1>
    <p>正文里有 <strong>重点</strong></p>
    ![示意图](https://example.com/a.png)
    [参考链接](https://example.com)
    """
    plain = LLMService.strip_markup(content)

    assert "<" not in plain
    assert "标题" in plain
    assert "重点" in plain
    assert "https://example.com/a.png" not in plain, "图片 URL 应当被丢弃"
    assert "参考链接" in plain, "链接文字应当保留"
    assert "https://example.com)" not in plain


def test_strip_markup_empty_result():
    """只有标签没有文字时清洗后为空。"""
    assert LLMService.strip_markup("<div></div>") == ""


def test_clean_summary_strips_quotes_and_prefix():
    """摘要清洗：去成对引号、去「摘要：」前缀、截断到 255。"""
    assert LLMService._clean_summary('"这是摘要"') == "这是摘要"
    assert LLMService._clean_summary("「中文引号」") == "中文引号"
    assert LLMService._clean_summary("摘要：正式内容") == "正式内容"
    assert LLMService._clean_summary("总结: 正式内容") == "正式内容"

    long_text = "字" * 300
    assert len(LLMService._clean_summary(long_text)) == 255


# ============================================================
# 配置 CRUD
# ============================================================


def test_create_requires_working_connection(client, fake_llm):
    """新建时测试连接失败 → 400，且库里不留记录。"""
    fake_llm["ok"] = False
    fake_llm["error"] = "LLM 返回异常状态码 401: Invalid API key"

    resp = client.post(
        f"{API}/admin/llm-configs",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-bad-key-123456",
            "model": "deepseek-chat",
        },
        headers=_admin_headers(client),
    )
    assert resp.status_code == 400
    assert "配置不可用，测试连接失败" in resp.json()["message"]

    # 库里不该有记录
    resp = client.get(f"{API}/admin/llm-configs", headers=_admin_headers(client))
    assert resp.json()["data"] == []


def test_create_and_list(client, fake_llm):
    """测通后入库，列表返回脱敏密钥。"""
    fake_llm["ok"] = True

    resp = client.post(
        f"{API}/admin/llm-configs",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-1234567890abcdef",
            "model": "deepseek-chat",
            "timeout_sec": 45,
        },
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["api_key_masked"] == "sk-****cdef"
    assert "sk-1234567890abcdef" not in resp.text, "明文密钥绝不能出现在响应里"
    assert data["type"] == 1
    assert data["timeout_sec"] == 45
    # 响应里没有 dimension（新库无此列）
    assert "dimension" not in data

    # 列表
    resp = client.get(f"{API}/admin/llm-configs", headers=_admin_headers(client))
    assert resp.status_code == 200
    configs = resp.json()["data"]
    assert isinstance(configs, list)
    assert len(configs) == 1
    assert configs[0]["id"] == data["id"]


def test_get_detail(client, fake_llm):
    """详情接口。"""
    fake_llm["ok"] = True
    created = client.post(
        f"{API}/admin/llm-configs",
        json={"base_url": "https://x/v1", "api_key": "sk-aaaaaaaaaaaa", "model": "m"},
        headers=_admin_headers(client),
    ).json()["data"]

    resp = client.get(f"{API}/admin/llm-configs/{created['id']}", headers=_admin_headers(client))
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == created["id"]


def test_get_missing_returns_404(client):
    """不存在的配置 → 404「配置不存在」。"""
    resp = client.get(f"{API}/admin/llm-configs/99999999", headers=_admin_headers(client))
    assert resp.status_code == 404
    assert resp.json()["message"] == "配置不存在"


def test_update_only_runtime_params(client, fake_llm):
    """更新只改运行参数，连接信息保持原样。"""
    fake_llm["ok"] = True
    created = client.post(
        f"{API}/admin/llm-configs",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-1234567890abcdef",
            "model": "deepseek-chat",
        },
        headers=_admin_headers(client),
    ).json()["data"]

    # 即使请求体里塞了 base_url / api_key / model，也应被忽略（schema 里没这些字段）
    resp = client.put(
        f"{API}/admin/llm-configs/{created['id']}",
        json={
            "timeout_sec": 60,
            "max_tokens": 4096,
            "temperature": 0.7,
            "status": 0,
            "base_url": "https://evil/v1",
            "api_key": "sk-hacked",
        },
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, resp.text

    data = client.get(
        f"{API}/admin/llm-configs/{created['id']}", headers=_admin_headers(client)
    ).json()["data"]
    assert data["timeout_sec"] == 60
    assert data["max_tokens"] == 4096
    assert data["temperature"] == 0.7
    assert data["status"] == 0
    assert data["base_url"] == "https://api.deepseek.com/v1", "base_url 不可被改"
    assert data["api_key_masked"] == "sk-****cdef", "api_key 不可被改"


def test_delete_config(client, fake_llm):
    """删除后查不到。"""
    fake_llm["ok"] = True
    created = client.post(
        f"{API}/admin/llm-configs",
        json={"base_url": "https://x/v1", "api_key": "sk-bbbbbbbbbbbb", "model": "m"},
        headers=_admin_headers(client),
    ).json()["data"]

    resp = client.delete(f"{API}/admin/llm-configs/{created['id']}", headers=_admin_headers(client))
    assert resp.status_code == 200

    resp = client.get(f"{API}/admin/llm-configs/{created['id']}", headers=_admin_headers(client))
    assert resp.status_code == 404


def _query(client, sql: str, params: dict) -> list[tuple]:
    """同步执行查询。"""
    import asyncio

    from sqlalchemy import text

    from app.db.database import Database

    db = Database(client.app.state.settings)

    async def _run() -> list[tuple]:
        async with db.session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = [tuple(r) for r in result.fetchall()]
        await db.dispose()
        return rows

    return asyncio.run(_run())


def test_endpoints_require_admin(client):
    """普通用户访问 → 403。"""
    from tests.helpers import register_and_login

    _, _, token = register_and_login(client)
    resp = client.get(f"{API}/admin/llm-configs", headers=auth_headers(token))
    assert resp.status_code == 403


# ============================================================
# 测试连接
# ============================================================


def test_connection_success_returns_200(client, fake_llm):
    """测试连接的成败都走 200，前端看 data.ok。"""
    fake_llm["ok"] = True
    resp = client.post(
        f"{API}/admin/llm-configs/test",
        json={"base_url": "https://x/v1", "model": "m", "api_key": "sk-1234567890"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["reply"] == "连接成功"
    assert data["latency_ms"] >= 0


def test_connection_failure_still_200(client, fake_llm):
    """连接失败也是 200，只是 ok=false。"""
    fake_llm["ok"] = False
    fake_llm["error"] = "LLM 返回异常状态码 401: Invalid API key"

    resp = client.post(
        f"{API}/admin/llm-configs/test",
        json={"base_url": "https://x/v1", "model": "m", "api_key": "sk-wrong"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, "连不通不该返回 500"
    data = resp.json()["data"]
    assert data["ok"] is False
    assert "401" in data["error"]


def test_test_route_not_swallowed_by_id(client, fake_llm):
    """`POST /llm-configs/test` 不能被 `/{config_id}` 吃掉。

    虽然是 POST 而详情是 GET，但这条测试守住「静态路径在前」的约定。
    """
    fake_llm["ok"] = True
    resp = client.post(
        f"{API}/admin/llm-configs/test",
        json={"base_url": "https://x/v1", "model": "m", "api_key": "sk-1"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, f"被吃掉了：{resp.status_code} {resp.text}"


# ============================================================
# 摘要
# ============================================================


def _create_config(client) -> int:
    """建一条可用的配置，返回 ID。"""
    resp = client.post(
        f"{API}/admin/llm-configs",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-1234567890abcdef",
            "model": "deepseek-chat",
        },
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def test_generate_summary(client, fake_llm):
    """摘要生成：返回清洗后的文本，且不落库。"""
    fake_llm["ok"] = True
    config_id = _create_config(client)
    fake_llm["summary"] = "摘要：这篇文章讲了一次从 Go 到 Python 的重写。"

    resp = client.post(
        f"{API}/admin/articles/generate-summary",
        json={"config_id": config_id, "title": "重写实践", "content": "<p>正文内容</p>"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 200, resp.text

    summary = resp.json()["data"]["summary"]
    assert summary == "这篇文章讲了一次从 Go 到 Python 的重写。", "前缀应当被剥掉"

    # 不落库：接口只返回文本，articles 表不该因为这次调用多出任何记录
    rows = _query(client, "SELECT COUNT(*) FROM articles WHERE summary LIKE '%重写%'", {})
    assert rows[0][0] == 0, "摘要不该被写进 articles"


def test_generate_summary_disabled_config(client, fake_llm):
    """配置被禁用 → 400。"""
    fake_llm["ok"] = True
    config_id = _create_config(client)

    client.put(
        f"{API}/admin/llm-configs/{config_id}",
        json={"status": 0},
        headers=_admin_headers(client),
    )

    resp = client.post(
        f"{API}/admin/articles/generate-summary",
        json={"config_id": config_id, "title": "t", "content": "<p>内容</p>"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 400
    assert "已禁用" in resp.json()["message"]


def test_generate_summary_empty_content(client, fake_llm):
    """正文清洗后为空 → 400「文章内容为空」。"""
    fake_llm["ok"] = True
    config_id = _create_config(client)

    resp = client.post(
        f"{API}/admin/articles/generate-summary",
        json={"config_id": config_id, "title": "t", "content": "<div></div>"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "文章内容为空"


def test_generate_summary_missing_config(client):
    """配置不存在 → 404。"""
    resp = client.post(
        f"{API}/admin/articles/generate-summary",
        json={"config_id": 99999999, "title": "t", "content": "内容"},
        headers=_admin_headers(client),
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "配置不存在"


def test_generate_summary_truncates_long_content(client, fake_llm):
    """超长正文会被截断到 8000 字符再送给模型。"""
    fake_llm["ok"] = True
    config_id = _create_config(client)

    captured: dict[str, object] = {}

    async def spy_chat(self, **kwargs):
        captured["messages"] = kwargs["messages"]
        return "摘要"

    import app.integrations.llm_client as mod

    original = mod.LLMClient.chat
    mod.LLMClient.chat = spy_chat
    try:
        resp = client.post(
            f"{API}/admin/articles/generate-summary",
            json={"config_id": config_id, "title": "长文", "content": "字" * 20000},
            headers=_admin_headers(client),
        )
        assert resp.status_code == 200, resp.text
    finally:
        mod.LLMClient.chat = original

    prompt = captured["messages"][0]["content"]
    # prompt 里含模板文案，正文部分应当不超过 8000
    body = prompt.split("正文：", 1)[1]
    assert len(body.strip()) <= 8000, f"正文未截断，实际 {len(body.strip())} 字符"
