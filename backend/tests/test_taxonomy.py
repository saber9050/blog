"""分类与标签测试。

两个实体的 CRUD 形状一样，但**删除语义不同**，这是本模块最需要覆盖的点：
- 分类：有文章就拒绝删除
- 标签：有文章也允许，清掉关联即可
"""

import pytest

from tests.helpers import (
    auth_headers,
    exec_sql,
    login,
    new_name,
    purge_test_users,
)

API = "/api/v1"
TEST_PREFIX = "__t_"


@pytest.fixture(scope="module")
def client(live_client):
    """复用 conftest 的 live_client。"""
    return live_client


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清理分类、标签、测试文章。"""
    _purge(client)
    yield
    _purge(client)


def _purge(client) -> None:
    """按名称前缀删掉测试数据。"""
    purge_test_users(client)
    exec_sql(
        client,
        "DELETE FROM tag_articles WHERE article_id IN "
        "(SELECT id FROM articles WHERE title LIKE :p)",
        {"p": f"{TEST_PREFIX}%"},
    )
    exec_sql(client, "DELETE FROM articles WHERE title LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM categorys WHERE category_name LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM tags WHERE tag_name LIKE :p", {"p": f"{TEST_PREFIX}%"})


def _admin_headers(client) -> dict[str, str]:
    """登录默认管理员。"""
    settings = client.app.state.settings
    data = login(client, settings.admin.account, settings.admin.password.get_secret_value())
    return auth_headers(data["access_token"])


def _new_label() -> str:
    """生成带前缀的唯一名称。"""
    return TEST_PREFIX + new_name()


def _create_category(client, headers, name: str, status: int = 1) -> int:
    """建一个分类，返回 ID。"""
    resp = client.post(
        f"{API}/admin/categories", json={"name": name, "status": status}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def _create_tag(client, headers, name: str, status: int = 1) -> int:
    """建一个标签，返回 ID。"""
    resp = client.post(f"{API}/admin/tags", json={"name": name, "status": status}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


# ============================================================
# 前台
# ============================================================


def test_public_list_returns_array(client):
    """前台列表的 data 是数组，不是分页对象。"""
    headers = _admin_headers(client)
    name = _new_label()
    _create_category(client, headers, name)

    resp = client.get(f"{API}/categories")
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert isinstance(data, list), "前台列表必须是数组"
    assert any(item["name"] == name for item in data)
    # 每项只有 id 与 name
    assert set(data[0]) == {"id", "name"}


def test_public_list_excludes_disabled(client):
    """禁用的不出现。"""
    headers = _admin_headers(client)
    hidden = _new_label()
    _create_category(client, headers, hidden, status=0)

    resp = client.get(f"{API}/categories")
    names = [item["name"] for item in resp.json()["data"]]
    assert hidden not in names


def test_count_only_enabled(client):
    """数量只统计启用的。"""
    headers = _admin_headers(client)
    before = client.get(f"{API}/categories/count").json()["data"]["count"]

    _create_category(client, headers, _new_label(), status=1)
    assert client.get(f"{API}/categories/count").json()["data"]["count"] == before + 1

    _create_category(client, headers, _new_label(), status=0)
    assert client.get(f"{API}/categories/count").json()["data"]["count"] == before + 1


def test_tags_public_list(client):
    """标签前台列表与计数。"""
    headers = _admin_headers(client)
    name = _new_label()
    _create_tag(client, headers, name)

    resp = client.get(f"{API}/tags")
    assert resp.status_code == 200
    assert any(item["name"] == name for item in resp.json()["data"])

    assert client.get(f"{API}/tags/count").json()["data"]["count"] >= 1


# ============================================================
# 后台列表
# ============================================================


def test_admin_list_pagination_shape(client):
    """后台列表分页键是下划线 page_size。"""
    headers = _admin_headers(client)

    resp = client.get(
        f"{API}/admin/categories", params={"page": 1, "page_size": 5}, headers=headers
    )
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}
    assert data["page"] == 1
    assert data["page_size"] == 5


def test_admin_list_filters(client):
    """按关键词与状态筛选。"""
    headers = _admin_headers(client)
    name = _new_label()
    _create_category(client, headers, name, status=0)

    resp = client.get(
        f"{API}/admin/categories", params={"keyword": name, "status": 0}, headers=headers
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["name"] == name


def test_admin_endpoints_require_admin(client):
    """普通用户访问后台 → 403。"""
    from tests.helpers import register_and_login

    _, _, token = register_and_login(client)
    resp = client.get(f"{API}/admin/categories", headers=auth_headers(token))
    assert resp.status_code == 403


# ============================================================
# 新建 / 更新
# ============================================================


def test_create_strips_whitespace(client):
    """名称首尾空格会被 strip 掉（Go 版不 strip）。"""
    headers = _admin_headers(client)
    raw = f"  {_new_label()}  "

    resp = client.post(f"{API}/admin/categories", json={"name": raw, "status": 1}, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.get(f"{API}/admin/categories", params={"keyword": raw.strip()}, headers=headers)
    stored = resp.json()["data"]["list"][0]["name"]
    assert stored == raw.strip(), "入库的名称不应带首尾空格"


def test_create_rejects_duplicate_after_strip(client):
    """「名称」与「名称 」视为重复。"""
    headers = _admin_headers(client)
    name = _new_label()
    _create_category(client, headers, name)

    resp = client.post(
        f"{API}/admin/categories", json={"name": f"  {name}  ", "status": 1}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "分类名称已存在"


def test_create_rejects_blank_name(client):
    """全空格 → 400。"""
    headers = _admin_headers(client)
    resp = client.post(
        f"{API}/admin/categories", json={"name": "   ", "status": 1}, headers=headers
    )
    assert resp.status_code == 400


def test_update_excludes_self(client):
    """名称原样提交不报重复（查重排除自己）。"""
    headers = _admin_headers(client)
    name = _new_label()
    cid = _create_category(client, headers, name)

    resp = client.put(
        f"{API}/admin/categories/{cid}", json={"name": name, "status": 0}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    # 状态确实变了
    resp = client.get(f"{API}/admin/categories", params={"keyword": name}, headers=headers)
    assert resp.json()["data"]["list"][0]["status"] == 0


def test_update_rejects_duplicate(client):
    """改成别人的名称 → 400。"""
    headers = _admin_headers(client)
    name_a, name_b = _new_label(), _new_label()
    _create_category(client, headers, name_a)
    cid_b = _create_category(client, headers, name_b)

    resp = client.put(
        f"{API}/admin/categories/{cid_b}", json={"name": name_a, "status": 1}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "分类名称已存在"


def test_update_unknown_returns_404(client):
    """更新不存在的分类 → 404。"""
    headers = _admin_headers(client)
    resp = client.put(
        f"{API}/admin/categories/99999999",
        json={"name": _new_label(), "status": 1},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "分类不存在"


# ============================================================
# 删除：两个实体的核心差异
# ============================================================


def test_delete_empty_category(client):
    """空分类可以直接删（物理删除）。"""
    headers = _admin_headers(client)
    name = _new_label()
    cid = _create_category(client, headers, name)

    resp = client.delete(f"{API}/admin/categories/{cid}", headers=headers)
    assert resp.status_code == 200

    resp = client.get(f"{API}/admin/categories", params={"keyword": name}, headers=headers)
    assert resp.json()["data"]["total"] == 0


def test_delete_category_with_articles_is_rejected(client):
    """分类下有文章 → 400。"""
    headers = _admin_headers(client)
    name = _new_label()
    cid = _create_category(client, headers, name)
    _insert_article(client, title=_new_label(), category_id=cid)

    resp = client.delete(f"{API}/admin/categories/{cid}", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["message"] == "该分类下存在文章，无法删除"


def test_delete_category_ignores_soft_deleted_articles(client):
    """已软删的文章不该阻止分类删除。"""
    headers = _admin_headers(client)
    name = _new_label()
    cid = _create_category(client, headers, name)
    article_id = _insert_article(client, title=_new_label(), category_id=cid)

    exec_sql(client, "UPDATE articles SET deleted_at = NOW() WHERE id = :i", {"i": article_id})

    resp = client.delete(f"{API}/admin/categories/{cid}", headers=headers)
    assert resp.status_code == 200, "软删的文章不应阻止删除分类"


def test_delete_tag_with_articles_is_allowed(client):
    """标签下有文章也允许删，且关联被清干净。"""
    headers = _admin_headers(client)
    name = _new_label()
    tid = _create_tag(client, headers, name)
    article_id = _insert_article(client, title=_new_label(), category_id=None, tag_id=tid)

    resp = client.delete(f"{API}/admin/tags/{tid}", headers=headers)
    assert resp.status_code == 200, resp.text

    # 关联行应被清掉
    rows = _query(client, "SELECT COUNT(*) AS c FROM tag_articles WHERE tag_id = :t", {"t": tid})
    assert rows[0][0] == 0, "删除标签后不应残留关联"

    # 文章本身还在
    rows = _query(client, "SELECT COUNT(*) AS c FROM articles WHERE id = :i", {"i": article_id})
    assert rows[0][0] == 1, "删标签不该删文章"


def test_delete_unknown_returns_404(client):
    """删不存在 → 404，文案区分分类与标签。"""
    headers = _admin_headers(client)

    resp = client.delete(f"{API}/admin/categories/99999999", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["message"] == "分类不存在"

    resp = client.delete(f"{API}/admin/tags/99999999", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["message"] == "标签不存在"


# ============================================================
# 测试数据工具
# ============================================================


def _insert_article(
    client, *, title: str, category_id: int | None, tag_id: int | None = None
) -> int:
    """直接插一篇文章（P3 还没有文章接口）。

    分类必填：没有分类时临时建一个，避免 `type_id` 为空。
    """
    if category_id is None:
        headers = _admin_headers(client)
        category_id = _create_category(client, headers, _new_label())

    user_id = _query(client, "SELECT id FROM users WHERE role_id = 1 LIMIT 1", {})[0][0]
    exec_sql(
        client,
        "INSERT INTO articles (user_id, title, content, type_id, status) "
        "VALUES (:u, :t, '正文', :c, 1)",
        {"u": user_id, "t": title, "c": category_id},
    )
    article_id = _query(client, "SELECT id FROM articles WHERE title = :t", {"t": title})[0][0]

    if tag_id is not None:
        exec_sql(
            client,
            "INSERT INTO tag_articles (article_id, tag_id) VALUES (:a, :t)",
            {"a": article_id, "t": tag_id},
        )
    return article_id


def _query(client, sql: str, params: dict) -> list[tuple]:
    """同步执行查询，返回全部行。"""
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
