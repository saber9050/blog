"""文章前台接口（6 条）。

路由顺序有个硬要求：`/random` 与 `/stats` 必须注册在 `/{article_id}` 之前。
FastAPI 按注册顺序线性匹配，`{article_id}` 能匹配任意字符串，
`int("random")` 转换失败会直接返回 422，**不会回退去试下一条**。
Go 的 gin 用路由树自动优先静态路径，所以旧代码写反了也没事 —— 这是重写引入的坑。
"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import (
    CurrentUser,
    get_article_service,
    get_current_user,
    get_optional_user,
)
from app.core.response import ResponseBuilder
from app.schemas.article import ArticleListQuery
from app.services.article.article_service import ArticleService, Viewer


def _parse_query(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    sort: str = Query(default="latest", pattern="^(latest|popular)$"),
    category_id: int | None = Query(default=None),
    tag_ids: str = Query(default=""),
    keyword: str = Query(default=""),
) -> ArticleListQuery:
    """把 query 参数收成对象。"""
    return ArticleListQuery(
        page=page,
        page_size=page_size,
        sort=sort,
        category_id=category_id,
        tag_ids=tag_ids,
        keyword=keyword,
    )


def _to_viewer(user: CurrentUser | None) -> Viewer | None:
    """把 HTTP 层的 CurrentUser 转成 service 认识的 Viewer。

    为什么要转：service 不该 import `app.core.deps`（那是 HTTP 层），
    否则 service 单测就得造一个 Request 对象。
    """
    if user is None:
        return None
    return Viewer(user_id=user.user_id, is_admin=user.is_admin)


class ArticleController:
    """文章公开接口。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(prefix="/articles", tags=["文章"])
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        ⚠️ **顺序不能改**：静态路径必须在 `/{article_id}` 之前，
        否则 `/articles/random` 会被当成 `article_id="random"` → 422。
        """
        r = self.router
        r.add_api_route("", self.list_articles, methods=["GET"], summary="文章列表")
        # ---- 静态路径（必须在 {article_id} 之前）----
        r.add_api_route("/random", self.random_article, methods=["GET"], summary="随机一篇")
        r.add_api_route("/stats", self.site_stats, methods=["GET"], summary="站点统计")
        # ---- 动态路径 ----
        r.add_api_route("/{article_id}", self.get_detail, methods=["GET"], summary="文章详情")
        r.add_api_route("/{article_id}/like", self.like, methods=["POST"], summary="点赞")
        r.add_api_route("/{article_id}/like", self.unlike, methods=["DELETE"], summary="取消点赞")

    async def list_articles(
        self,
        query: ArticleListQuery = Depends(_parse_query),
        user: CurrentUser | None = Depends(get_optional_user),
        service: ArticleService = Depends(get_article_service),
    ):
        """文章列表。带 token 时 `is_liked` 才准。"""
        result = await service.list_public(query, viewer_id=user.user_id if user else None)
        return ResponseBuilder.ok(result)

    async def random_article(
        self,
        service: ArticleService = Depends(get_article_service),
    ):
        """随机一篇已发布文章的 ID。"""
        article_id = await service.random_id()
        return ResponseBuilder.ok({"id": article_id})

    async def site_stats(
        self,
        service: ArticleService = Depends(get_article_service),
    ):
        """站点统计：文章数、总浏览、总点赞。"""
        result = await service.stats()
        return ResponseBuilder.ok(result)

    async def get_detail(
        self,
        article_id: int,
        user: CurrentUser | None = Depends(get_optional_user),
        service: ArticleService = Depends(get_article_service),
    ):
        """文章详情。每次请求浏览量 +1。"""
        result = await service.get_detail(article_id, _to_viewer(user))
        return ResponseBuilder.ok(result)

    async def like(
        self,
        article_id: int,
        user: CurrentUser = Depends(get_current_user),
        service: ArticleService = Depends(get_article_service),
    ):
        """点赞。未登录返回 401「请提供认证令牌」。"""
        await service.like(article_id, user.user_id)
        return ResponseBuilder.ok(None)

    async def unlike(
        self,
        article_id: int,
        user: CurrentUser = Depends(get_current_user),
        service: ArticleService = Depends(get_article_service),
    ):
        """取消点赞。"""
        await service.unlike(article_id, user.user_id)
        return ResponseBuilder.ok(None)
