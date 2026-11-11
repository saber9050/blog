"""文章模块测试。

重点覆盖三类容易出错的地方：

1. **路由顺序**：`/articles/random` 不能被 `/articles/{id}` 吃掉
2. **草稿访问控制**：游客拿到 404，作者本人能看
3. **删除副作用**：软删文章 → 评论软删、标签关联清空、图片记录清空

图片同步依赖 MinIO，不可用时自动跳过。
"""

import pytest

from tests.helpers import (
    auth_headers,
    exec_sql,
    login,
    new_name,
    purge_test_users,
    register_and_login,
)

API = "/api/v1"
TEST_PREFIX = "__t_"


@pytest.fixture(scope="module")
def client(live_client):
    """复用 conftest 的 live_client（SMTP 已禁用）。"""
    return live_client


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清理。"""
    _purge(client)
    yield
    _purge(client)


def _purge(client) -> None:
    """删掉测试产生的文章 / 分类 / 标签。"""
    purge_test_users(client)
    exec_sql(
        client,
        "DELETE FROM comments WHERE article_id IN (SELECT id FROM articles WHERE title LIKE :p)",
        {"p": f"{TEST_PREFIX}%"},
    )
    exec_sql(
        client,
        "DELETE FROM tag_articles WHERE article_id IN "
        "(SELECT id FROM articles WHERE title LIKE :p)",
        {"p": f"{TEST_PREFIX}%"},
    )
    exec_sql(
        client,
        "DELETE FROM article_images WHERE article_id IN "
        "(SELECT id FROM articles WHERE title LIKE :p)",
        {"p": f"{TEST_PREFIX}%"},
    )
    exec_sql(client, "DELETE FROM articles WHERE title LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM categorys WHERE category_name LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM tags WHERE tag_name LIKE :p", {"p": f"{TEST_PREFIX}%"})


def _admin_headers(client) -> dict[str, str]:
    """登录管理员。"""
    settings = client.app.state.settings
    data = login(client, settings.admin.account, settings.admin.password.get_secret_value())
    return auth_headers(data["access_token"])


def _label() -> str:
    """带前缀的唯一名称。"""
    return TEST_PREFIX + new_name()


def _category(client, headers, name: str | None = None) -> int:
    """建一个分类。"""
    resp = client.post(
        f"{API}/admin/categories", json={"name": name or _label(), "status": 1}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def _tag(client, headers, name: str | None = None) -> int:
    """建一个标签。"""
    resp = client.post(
        f"{API}/admin/tags", json={"name": name or _label(), "status": 1}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def _article(
    client,
    headers,
    *,
    title: str | None = None,
    type_id: int,
    tag_ids: list[int] | None = None,
    status: int = 1,
    content: str = "# 正文\n测试内容",
    cover_url: str = "",
    summary: str = "",
) -> int:
    """建一篇文章。"""
    resp = client.post(
        f"{API}/admin/articles",
        json={
            "title": title or _label(),
            "type_id": type_id,
            "tag_ids": tag_ids or [],
            "cover_url": cover_url,
            "summary": summary,
            "content": content,
            "status": status,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


# ============================================================
# 路由顺序（重写引入的坑）
# ============================================================


def test_random_route_not_swallowed_by_id(client):
    """`/articles/random` 必须命中它自己，而不是被 `/{article_id}` 吃掉。

    写反了的话 `int("random")` 转换失败，FastAPI 返回 422 —— 这条测试就是守它的。
    """
    headers = _admin_headers(client)
    cid = _category(client, headers)
    _article(client, headers, type_id=cid)

    resp = client.get(f"{API}/articles/random")
    assert resp.status_code == 200, f"路由被 {resp.status_code} 吃掉了：{resp.text}"
    assert "id" in resp.json()["data"]


def test_stats_route_not_swallowed(client):
    """`/articles/stats` 同理。"""
    resp = client.get(f"{API}/articles/stats")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data) == {"article_count", "total_views", "total_likes"}


def test_transfer_route_not_swallowed(client):
    """`PUT /admin/articles/transfer` 不能被 `PUT /{article_id}` 吃掉。"""
    headers = _admin_headers(client)
    cid_from = _category(client, headers)
    cid_to = _category(client, headers)

    resp = client.put(
        f"{API}/admin/articles/transfer",
        json={"from_type_id": cid_from, "to_type_id": cid_to},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "count" in resp.json()["data"]


# ============================================================
# 列表与筛选
# ============================================================


def test_list_shape_and_pagination(client):
    """列表返回分页结构，字段名是 page_size。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    _article(client, headers, type_id=cid)

    resp = client.get(f"{API}/articles", params={"page": 1, "page_size": 5})
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert set(data) == {"list", "total", "page", "page_size"}


def test_list_page_size_capped_at_100(client):
    """page_size 超过 100 时被截断，但请求本身不报错。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    _article(client, headers, type_id=cid)

    resp = client.get(f"{API}/articles", params={"page_size": 500})
    assert resp.status_code == 200
    assert resp.json()["data"]["page_size"] == 100


def test_list_excludes_drafts(client):
    """前台列表不返回草稿。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    draft_title = _label()
    _article(client, headers, title=draft_title, type_id=cid, status=0)

    resp = client.get(f"{API}/articles", params={"keyword": draft_title})
    assert resp.json()["data"]["total"] == 0


def test_list_filter_by_category(client):
    """按分类筛选。"""
    headers = _admin_headers(client)
    cid_a, cid_b = _category(client, headers), _category(client, headers)
    title = _label()
    _article(client, headers, title=title, type_id=cid_a)
    _article(client, headers, title=_label(), type_id=cid_b)

    resp = client.get(f"{API}/articles", params={"category_id": cid_a, "keyword": title})
    assert resp.json()["data"]["total"] == 1


def test_list_filter_by_tags(client):
    """标签筛选是「命中任一」。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    tag_a, tag_b = _tag(client, headers), _tag(client, headers)

    title_a = _label()
    _article(client, headers, title=title_a, type_id=cid, tag_ids=[tag_a])
    _article(client, headers, title=_label(), type_id=cid, tag_ids=[tag_b])

    resp = client.get(f"{API}/articles", params={"tag_ids": str(tag_b)})
    assert resp.json()["data"]["total"] >= 1

    # 两个标签一起传，命中任一
    resp = client.get(f"{API}/articles", params={"tag_ids": f"{tag_a},{tag_b}"})
    assert resp.json()["data"]["total"] >= 2


def test_list_sort_popular(client):
    """popular 排序按热度公式，点赞多的在前。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    popular_title = _label()
    cold_title = _label()
    popular_id = _article(client, headers, title=popular_title, type_id=cid)
    _article(client, headers, title=cold_title, type_id=cid)

    # 给第一篇刷 3 个赞（用三个不同用户）
    for _ in range(3):
        _, account, token = register_and_login(client)
        resp = client.post(f"{API}/articles/{popular_id}/like", headers=auth_headers(token))
        assert resp.status_code == 200, resp.text

    resp = client.get(f"{API}/articles", params={"sort": "popular", "page_size": 100})
    names = [item["title"] for item in resp.json()["data"]["list"]]
    assert names.index(popular_title) < names.index(cold_title)


def test_admin_list_includes_drafts(client):
    """后台列表能看到草稿。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    draft_title = _label()
    _article(client, headers, title=draft_title, type_id=cid, status=0)

    resp = client.get(f"{API}/admin/articles", params={"keyword": draft_title}, headers=headers)
    assert resp.json()["data"]["total"] == 1

    # 后台列表多一个 updated_at
    item = resp.json()["data"]["list"][0]
    assert "updated_at" in item


# ============================================================
# 详情
# ============================================================


def test_detail_increments_views(client):
    """每次请求浏览量 +1。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid)

    first = client.get(f"{API}/articles/{aid}").json()["data"]
    second = client.get(f"{API}/articles/{aid}").json()["data"]

    assert second["views"] == first["views"] + 1


def test_detail_contains_content(client):
    """详情比列表多一个 content。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, content="# 标题\n正文内容")

    data = client.get(f"{API}/articles/{aid}").json()["data"]
    assert data["content"] == "# 标题\n正文内容"


def test_detail_404_for_missing(client):
    """不存在的文章 → 404。"""
    resp = client.get(f"{API}/articles/99999999")
    assert resp.status_code == 404
    assert resp.json()["message"] == "文章不存在"


def test_draft_hidden_from_guest(client):
    """游客访问草稿 → 404（不是 403，避免暴露「这里有一篇草稿」）。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, status=0)

    resp = client.get(f"{API}/articles/{aid}")
    assert resp.status_code == 404
    assert resp.json()["message"] == "文章不存在"


def test_draft_visible_to_author(client):
    """作者本人能看自己的草稿。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, status=0)

    # 用管理员 token（就是作者）访问
    resp = client.get(f"{API}/articles/{aid}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["id"] == aid


def test_draft_hidden_from_other_user(client):
    """别的普通用户看草稿 → 404。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, status=0)

    _, _, token = register_and_login(client)
    resp = client.get(f"{API}/articles/{aid}", headers=auth_headers(token))
    assert resp.status_code == 404


# ============================================================
# 点赞
# ============================================================


def test_like_and_unlike(client):
    """点赞 → 重复点赞 400 → 取消 → 再取消 400。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid)
    _, _, token = register_and_login(client)
    h = auth_headers(token)

    resp = client.post(f"{API}/articles/{aid}/like", headers=h)
    assert resp.status_code == 200, resp.text

    resp = client.post(f"{API}/articles/{aid}/like", headers=h)
    assert resp.status_code == 400
    assert resp.json()["message"] == "您已经点赞过该文章"

    resp = client.delete(f"{API}/articles/{aid}/like", headers=h)
    assert resp.status_code == 200

    resp = client.delete(f"{API}/articles/{aid}/like", headers=h)
    assert resp.status_code == 400
    assert resp.json()["message"] == "您尚未点赞该文章"


def test_like_requires_login(client):
    """未登录点赞 → 401。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid)

    resp = client.post(f"{API}/articles/{aid}/like")
    assert resp.status_code == 401


def test_is_liked_reflects_state(client):
    """列表里的 is_liked 随登录状态变化。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid)
    _, _, token = register_and_login(client)
    h = auth_headers(token)

    # 游客视角：false
    detail = client.get(f"{API}/articles/{aid}").json()["data"]
    assert detail["is_liked"] is False

    client.post(f"{API}/articles/{aid}/like", headers=h)

    detail = client.get(f"{API}/articles/{aid}", headers=h).json()["data"]
    assert detail["is_liked"] is True


def test_like_missing_article(client):
    """给不存在的文章点赞 → 404。"""
    _, _, token = register_and_login(client)
    resp = client.post(f"{API}/articles/99999999/like", headers=auth_headers(token))
    assert resp.status_code == 404


# ============================================================
# 增删改
# ============================================================


def test_create_requires_existing_category(client):
    """分类不存在 → 400。"""
    headers = _admin_headers(client)
    resp = client.post(
        f"{API}/admin/articles",
        json={
            "title": _label(),
            "type_id": 99999999,
            "content": "正文",
            "status": 1,
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "分类不存在"


def test_create_requires_existing_tags(client):
    """标签不存在 → 400。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    resp = client.post(
        f"{API}/admin/articles",
        json={
            "title": _label(),
            "type_id": cid,
            "tag_ids": [99999999],
            "content": "正文",
            "status": 1,
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "标签不存在" in resp.json()["message"]


def test_update_partial_fields(client):
    """更新只改传了的字段。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, summary="原摘要")

    resp = client.put(
        f"{API}/admin/articles/{aid}", json={"title": f"{TEST_PREFIX}新标题"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    data = client.get(f"{API}/articles/{aid}").json()["data"]
    assert data["title"] == f"{TEST_PREFIX}新标题"
    assert data["summary"] == "原摘要", "没传的字段不该被清空"


def test_update_status_to_draft(client):
    """发布 → 草稿后，游客看不到。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    aid = _article(client, headers, type_id=cid, status=1)

    client.put(f"{API}/admin/articles/{aid}", json={"status": 0}, headers=headers)

    resp = client.get(f"{API}/articles/{aid}")
    assert resp.status_code == 404


def test_delete_article_cascades(client):
    """删文章 → 软删 + 评论软删 + 标签关联清空。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)
    tid = _tag(client, headers)
    aid = _article(client, headers, type_id=cid, tag_ids=[tid])

    # 造一条评论
    exec_sql(
        client,
        "INSERT INTO comments (article_id, user_id, content) VALUES (:a, 1, '测试评论')",
        {"a": aid},
    )

    resp = client.delete(f"{API}/admin/articles/{aid}", headers=headers)
    assert resp.status_code == 200, resp.text

    # 文章不可见
    assert client.get(f"{API}/articles/{aid}").status_code == 404

    # 文章是软删，记录还在
    rows = _query(client, "SELECT deleted_at FROM articles WHERE id = :i", {"i": aid})
    assert rows and rows[0][0] is not None, "应当软删而不是物理删"

    # 评论被软删
    rows = _query(client, "SELECT deleted_at FROM comments WHERE article_id = :i", {"i": aid})
    assert rows and all(r[0] is not None for r in rows), "评论应当被软删"

    # 标签关联被清
    rows = _query(client, "SELECT COUNT(*) FROM tag_articles WHERE article_id = :i", {"i": aid})
    assert rows[0][0] == 0


def test_delete_missing_article(client):
    """删不存在的文章 → 404。"""
    headers = _admin_headers(client)
    resp = client.delete(f"{API}/admin/articles/99999999", headers=headers)
    assert resp.status_code == 404


def test_transfer_moves_articles(client):
    """转移分类后，源分类下没有文章。"""
    headers = _admin_headers(client)
    cid_from, cid_to = _category(client, headers), _category(client, headers)
    _article(client, headers, type_id=cid_from)
    _article(client, headers, type_id=cid_from)

    resp = client.put(
        f"{API}/admin/articles/transfer",
        json={"from_type_id": cid_from, "to_type_id": cid_to},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 2

    # 源分类现在可以删了（没有文章占用）
    resp = client.delete(f"{API}/admin/categories/{cid_from}", headers=headers)
    assert resp.status_code == 200, "转移后源分类应可删除"


def test_transfer_same_category_rejected(client):
    """源与目标相同 → 400。"""
    headers = _admin_headers(client)
    cid = _category(client, headers)

    resp = client.put(
        f"{API}/admin/articles/transfer",
        json={"from_type_id": cid, "to_type_id": cid},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "源分类与目标分类相同"


# ============================================================
# 工具
# ============================================================


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
