"""评论与关于页测试。

评论部分的核心验证点：

1. **total 与列表口径一致**（都含已删）—— Go 版这里是 bug
2. **删一级评论级联删回复**
3. **已删评论的 content 必须为空**（否则接口成了软删数据泄露通道）
4. 一级列表 DESC / 二级列表 ASC（方向相反）
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
    """复用 conftest 的 live_client。"""
    return live_client


@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    """测试前后清理评论、文章、分类。"""
    _purge(client)
    yield
    _purge(client)


def _purge(client) -> None:
    """删掉测试数据。"""
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
    exec_sql(client, "DELETE FROM articles WHERE title LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM categorys WHERE category_name LIKE :p", {"p": f"{TEST_PREFIX}%"})
    exec_sql(client, "DELETE FROM abouts", {})


def _admin_headers(client) -> dict[str, str]:
    """登录管理员。"""
    settings = client.app.state.settings
    data = login(client, settings.admin.account, settings.admin.password.get_secret_value())
    return auth_headers(data["access_token"])


def _new_article(client) -> int:
    """直接插一篇文章（P4 接口已就绪，但这里不需要走 HTTP）。"""
    name = TEST_PREFIX + new_name()
    exec_sql(
        client,
        "INSERT INTO categorys (category_name, status) VALUES (:n, 1)",
        {"n": name},
    )
    cid = _query(client, "SELECT id FROM categorys WHERE category_name = :n", {"n": name})[0][0]
    exec_sql(
        client,
        "INSERT INTO articles (user_id, title, content, type_id, status) "
        "VALUES (1, :t, '正文', :c, 1)",
        {"t": name, "c": cid},
    )
    return _query(client, "SELECT id FROM articles WHERE title = :t", {"t": name})[0][0]


def _comment(
    client, headers, article_id: int, content: str, parent_id: int | None = None, reply_to: str = ""
) -> int:
    """发一条评论，返回 ID。"""
    payload: dict = {"content": content}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if reply_to:
        payload["reply_to_user_name"] = reply_to
    resp = client.post(f"{API}/articles/{article_id}/comments", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


# ============================================================
# 发表
# ============================================================


def test_create_comment_shape(client):
    """返回的 CommentItem 字段齐全，时间格式带 +08:00。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    resp = client.post(f"{API}/articles/{aid}/comments", json={"content": "写得很清楚"}, headers=h)
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert set(data) == {
        "id",
        "content",
        "user_id",
        "user_name",
        "avatar_url",
        "parent_id",
        "reply_to_name",
        "is_deleted",
        "created_at",
        "children_total",
    }
    assert data["parent_id"] is None
    assert data["is_deleted"] is False
    assert data["children_total"] == 0
    # 评论的时间格式带时区偏移，与文章的假 Z 不同
    assert data["created_at"].endswith("+08:00")


def test_create_requires_login(client):
    """未登录 → 401。"""
    aid = _new_article(client)
    resp = client.post(f"{API}/articles/{aid}/comments", json={"content": "x"})
    assert resp.status_code == 401


def test_create_reply(client):
    """回复一级评论，parent_id 与 reply_to_name 都写进去。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    parent_id = _comment(client, h, aid, "一级评论")
    resp = client.post(
        f"{API}/articles/{aid}/comments",
        json={"content": "回复内容", "parent_id": parent_id, "reply_to_user_name": "某人"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["parent_id"] == parent_id
    assert data["reply_to_name"] == "某人"


def test_reply_to_missing_parent(client):
    """父评论不存在 → 404「资源不存在」。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    resp = client.post(
        f"{API}/articles/{aid}/comments",
        json={"content": "回复", "parent_id": 99999999},
        headers=h,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "资源不存在"


def test_reply_to_parent_of_other_article(client):
    """父评论属于别的文章 → 400。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid_a = _new_article(client)
    aid_b = _new_article(client)

    parent_id = _comment(client, h, aid_a, "A 文章的评论")

    resp = client.post(
        f"{API}/articles/{aid_b}/comments",
        json={"content": "跨文章回复", "parent_id": parent_id},
        headers=h,
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "父评论不属于该文章"


# ============================================================
# 列表
# ============================================================


def test_top_level_list_order_and_children(client):
    """一级列表按时间倒序，children_total 是子回复数。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    first = _comment(client, h, aid, "第一条")
    second = _comment(client, h, aid, "第二条")
    _comment(client, h, aid, "回复第一条", parent_id=first)

    resp = client.get(f"{API}/articles/{aid}/comments")
    assert resp.status_code == 200

    data = resp.json()["data"]
    ids = [item["id"] for item in data["list"]]
    # 倒序：后发的在前
    assert ids.index(second) < ids.index(first)

    target = next(item for item in data["list"] if item["id"] == first)
    assert target["children_total"] == 1


def test_top_level_total_includes_deleted(client):
    """total 与列表口径一致，都包含已删评论。

    这是 Go 版的 bug：计数不含已删、列表含，导致「total=3 但渲染 5 条」。
    """
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    _comment(client, h, aid, "保留")
    drop = _comment(client, h, aid, "待删")

    resp = client.delete(f"{API}/articles/{aid}/comments/{drop}", headers=h)
    assert resp.status_code == 200

    data = client.get(f"{API}/articles/{aid}/comments").json()["data"]
    assert data["total"] == 2, "total 应当包含已删评论"
    assert len(data["list"]) == 2, "列表也应当有 2 条"
    assert data["total"] == len(data["list"]), "total 与列表条数必须一致"

    # 已删的那条 content 为空
    deleted_item = next(item for item in data["list"] if item["id"] == drop)
    assert deleted_item["is_deleted"] is True
    assert deleted_item["content"] == "", "已删评论的内容必须清空"


def test_replies_list_ascending(client):
    """二级列表按时间正序（与一级的倒序相反）。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    parent_id = _comment(client, h, aid, "一级")
    r1 = _comment(client, h, aid, "回复1", parent_id=parent_id)
    r2 = _comment(client, h, aid, "回复2", parent_id=parent_id)

    resp = client.get(f"{API}/articles/{aid}/comments/{parent_id}/replies")
    assert resp.status_code == 200

    data = resp.json()["data"]
    ids = [item["id"] for item in data["list"]]
    assert ids.index(r1) < ids.index(r2), "回复应当按时间正序"
    assert all(item["children_total"] == 0 for item in data["list"])


def test_list_of_missing_article_returns_empty(client):
    """文章不存在时返回空列表，不报 404。"""
    resp = client.get(f"{API}/articles/99999999/comments")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


# ============================================================
# 删除与级联
# ============================================================


def test_delete_cascades_to_replies(client):
    """删一级评论会级联软删它的所有回复。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)

    parent_id = _comment(client, h, aid, "一级")
    _comment(client, h, aid, "回复1", parent_id=parent_id)
    _comment(client, h, aid, "回复2", parent_id=parent_id)

    resp = client.delete(f"{API}/articles/{aid}/comments/{parent_id}", headers=h)
    assert resp.status_code == 200

    # 三条全部软删
    rows = _query(
        client,
        "SELECT deleted_at FROM comments WHERE article_id = :a",
        {"a": aid},
    )
    assert len(rows) == 3
    assert all(r[0] is not None for r in rows), "子回复应当被级联软删"


def test_delete_by_other_user_forbidden(client):
    """别人删自己的评论 → 403。"""
    _, _, token_author = register_and_login(client)
    h_author = auth_headers(token_author)
    aid = _new_article(client)
    comment_id = _comment(client, h_author, aid, "我的评论")

    _, _, token_other = register_and_login(client)
    resp = client.delete(
        f"{API}/articles/{aid}/comments/{comment_id}", headers=auth_headers(token_other)
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == "禁止访问"


def test_admin_can_delete_others_comment(client):
    """管理员能删别人的评论。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)
    comment_id = _comment(client, h, aid, "路人评论")

    resp = client.delete(
        f"{API}/articles/{aid}/comments/{comment_id}", headers=_admin_headers(client)
    )
    assert resp.status_code == 200


def test_delete_missing_comment(client):
    """删不存在的评论 → 404。"""
    _, _, token = register_and_login(client)
    resp = client.delete(f"{API}/articles/1/comments/99999999", headers=auth_headers(token))
    assert resp.status_code == 404
    assert resp.json()["message"] == "资源不存在"


# ============================================================
# 后台
# ============================================================


def test_admin_list_excludes_deleted(client):
    """后台列表只返回未删除的评论。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)
    keep = _comment(client, h, aid, f"{TEST_PREFIX}保留")
    drop = _comment(client, h, aid, f"{TEST_PREFIX}待删")
    client.delete(f"{API}/articles/{aid}/comments/{drop}", headers=h)

    ah = _admin_headers(client)
    resp = client.get(f"{API}/admin/comments", params={"page_size": 50}, headers=ah)
    assert resp.status_code == 200

    ids = [item["id"] for item in resp.json()["data"]["list"]]
    assert keep in ids
    assert drop not in ids, "后台不该出现已删评论"
    # 后台时间格式是 ...Z
    assert resp.json()["data"]["list"][0]["created_at"].endswith("Z")


def test_admin_list_requires_admin(client):
    """普通用户 → 403。"""
    _, _, token = register_and_login(client)
    resp = client.get(f"{API}/admin/comments", headers=auth_headers(token))
    assert resp.status_code == 403


def test_admin_batch_delete(client):
    """批量删除，返回实际条数。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)
    c1 = _comment(client, h, aid, "批量1")
    c2 = _comment(client, h, aid, "批量2")

    ah = _admin_headers(client)
    resp = client.request("DELETE", f"{API}/admin/comments", json={"ids": [c1, c2]}, headers=ah)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["count"] == 2


def test_admin_batch_delete_empty_list(client):
    """空数组返回 0，不报错。"""
    resp = client.request(
        "DELETE", f"{API}/admin/comments", json={"ids": []}, headers=_admin_headers(client)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0


def test_admin_batch_delete_skips_missing(client):
    """不存在的 ID 被跳过，count 只算真实删除的。"""
    _, _, token = register_and_login(client)
    h = auth_headers(token)
    aid = _new_article(client)
    cid = _comment(client, h, aid, "真实存在")

    resp = client.request(
        "DELETE",
        f"{API}/admin/comments",
        json={"ids": [cid, 99999999]},
        headers=_admin_headers(client),
    )
    assert resp.json()["data"]["count"] == 1


# ============================================================
# 关于页
# ============================================================


def test_about_returns_contract_fields(client):
    """关于页字段名是 git_hub（不是 github）。"""
    resp = client.get(f"{API}/about")
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert set(data) == {
        "admin_name",
        "avatar_url",
        "email",
        "introduction",
        "tech_stack",
        "my_story",
        "why",
        "interest",
        "git_hub",  # 下划线，历史拼写
        "csdn",
    }
    # 空表时文字字段是 ""
    assert data["tech_stack"] == ""
    assert data["git_hub"] == ""


def test_about_update_and_read(client):
    """更新后能读回来，且部分更新不覆盖其他字段。"""
    ah = _admin_headers(client)

    resp = client.put(
        f"{API}/about",
        json={"tech_stack": "Go,Python", "git_hub": "https://github.com/saber9050"},
        headers=ah,
    )
    assert resp.status_code == 200, resp.text

    data = client.get(f"{API}/about").json()["data"]
    assert data["tech_stack"] == "Go,Python"
    assert data["git_hub"] == "https://github.com/saber9050"

    # 只改 csdn，其他字段保留
    client.put(f"{API}/about", json={"csdn": "https://blog.csdn.net/x"}, headers=ah)
    data = client.get(f"{API}/about").json()["data"]
    assert data["csdn"] == "https://blog.csdn.net/x"
    assert data["tech_stack"] == "Go,Python", "没传的字段不该被清空"


def test_about_update_requires_admin(client):
    """普通用户更新 → 403。"""
    _, _, token = register_and_login(client)
    resp = client.put(f"{API}/about", json={"why": "x"}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_about_404_without_admin(client):
    """连管理员都没有 → 404。

    用临时软删管理员的办法模拟，测完恢复。
    """
    exec_sql(client, "UPDATE users SET deleted_at = NOW() WHERE role_id = 1", {})
    try:
        resp = client.get(f"{API}/about")
        assert resp.status_code == 404
        assert resp.json()["message"] == "资源不存在"
    finally:
        exec_sql(client, "UPDATE users SET deleted_at = NULL WHERE role_id = 1", {})


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
