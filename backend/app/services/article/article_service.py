"""文章公共查询。

最核心的是 `_assemble`：把「一条主查询 + 三批批量查询」的结果拼成 DTO。
所有列表 / 详情都走它，保证 N+1 优化只有一处实现。
"""

import re

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsFileStorage
from app.core.timefmt import format_time_z
from app.db.models import Article
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import (
    AdminArticleItem,
    ArticleDetail,
    ArticleItem,
    ArticleListQuery,
    SiteStatsResponse,
    TaxonomyRef,
)

# 正文里的 <img src="...">。只匹配双引号或单引号包裹的 src
_IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)

# 单页上限：Go 版没有限制，这里加个兜底，防止一个 page_size=100000 把库拖死
MAX_PAGE_SIZE = 100


class ArticleService:
    """前台文章查询、详情、统计、点赞。"""

    def __init__(
        self,
        session: AsyncSession,
        repo: ArticleRepository,
        storage: SupportsFileStorage,
        settings: Settings,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 文章仓储。
            storage: 对象存储（拼头像/封面 URL、删图）。
            settings: 全局配置。
        """
        self._session = session
        self._repo = repo
        self._storage = storage
        self._settings = settings

    # ============================================================
    # 列表 / 详情
    # ============================================================

    async def list_public(self, query: ArticleListQuery, viewer_id: int | None) -> dict:
        """前台列表。

        `page_size` 在这里截断到 100 —— schema 只做 `ge=1`，
        上限属于业务策略，放 service 层便于将来调整。

        Args:
            query: 查询参数。
            viewer_id: 当前用户 ID，游客为 None（决定 `is_liked`）。

        Returns:
            `{list, total, page, page_size}`。
        """
        page_size = min(query.page_size, MAX_PAGE_SIZE)
        tag_ids = self._parse_tag_ids(query.tag_ids)

        rows, total = await self._repo.paginate_public(
            page=query.page,
            page_size=page_size,
            sort=query.sort,
            category_id=query.category_id,
            tag_ids=tag_ids,
            keyword=query.keyword,
        )
        items = await self._assemble(rows, viewer_id)
        return {
            "list": items,
            "total": total,
            "page": query.page,
            "page_size": page_size,
        }

    async def get_detail(self, article_id: int, viewer: "Viewer | None") -> ArticleDetail:
        """文章详情，并把浏览量 +1。

        草稿的访问控制在本轮加上了：非作者且非管理员访问草稿返回 **404**，
        而不是 403 —— 403 等于告诉对方「这里确实有一篇草稿」。

        Args:
            article_id: 文章 ID。
            viewer: 当前访问者，游客为 None。

        Returns:
            详情 DTO（含 content）。

        Raises:
            BizError: 404 文章不存在 / 无权限看草稿。
        """
        row = await self._repo.find_by_id(article_id)
        if row is None:
            raise BizError(ErrorCode.NOT_FOUND, "文章不存在")

        article: Article = row[0]
        if article.status != 1 and not self._can_view_draft(article, viewer):
            raise BizError(ErrorCode.NOT_FOUND, "文章不存在")

        # 浏览量 +1：包括作者本人和爬虫，Go 版就是这个行为。
        # 不做「同一 IP 5 分钟去重」——那需要额外的 Redis 结构，收益不大
        await self._repo.update_fields(article_id, views=(article.views or 0) + 1)
        await self._session.commit()

        items = await self._assemble([row], viewer.user_id if viewer else None)
        base = items[0]
        return ArticleDetail(**base.model_dump(), content=article.content)

    async def random_id(self) -> int:
        """随机一篇已发布文章的 ID。

        Raises:
            BizError: 404 站点还没有已发布文章。
        """
        article_id = await self._repo.random_published_id()
        if article_id is None:
            raise BizError(ErrorCode.NOT_FOUND, "暂无文章")
        return article_id

    async def stats(self) -> SiteStatsResponse:
        """站点统计。"""
        article_count, total_views, total_likes = await self._repo.site_stats()
        return SiteStatsResponse(
            article_count=article_count,
            total_views=total_views,
            total_likes=total_likes,
        )

    # ============================================================
    # 点赞
    # ============================================================

    async def like(self, article_id: int, user_id: int) -> None:
        """点赞。

        靠 `UNIQUE(article_id, user_id)` + 捕获 IntegrityError 保证幂等，
        不预检查 —— 检查与插入之间的窗口在并发下必然被打破。

        Raises:
            BizError: 404 文章不存在 / 400 重复点赞。
        """
        from sqlalchemy.exc import IntegrityError

        if await self._repo.find_published_id(article_id) is None:
            raise BizError(ErrorCode.NOT_FOUND, "文章不存在")

        try:
            await self._repo.insert_like(article_id, user_id)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise BizError(ErrorCode.BAD_REQUEST, "您已经点赞过该文章") from exc

    async def unlike(self, article_id: int, user_id: int) -> None:
        """取消点赞。

        Raises:
            BizError: 400 尚未点赞。
        """
        removed = await self._repo.delete_like(article_id, user_id)
        if removed == 0:
            raise BizError(ErrorCode.BAD_REQUEST, "您尚未点赞该文章")
        await self._session.commit()

    # ============================================================
    # 组装（N+1 优化的落点）
    # ============================================================

    async def _assemble(
        self,
        rows: list,
        viewer_id: int | None,
        *,
        with_updated_at: bool = False,
    ) -> list[ArticleItem]:
        """把查询结果拼成 DTO。

        调用次数固定：作者 1 次 + 分类 1 次 + 标签 1 次 + 点赞状态 1 次，
        与这一页有多少篇文章无关。

        Args:
            rows: `(Article, like_count, comment_count)` 的列表。
            viewer_id: 当前用户，游客为 None。
            with_updated_at: 后台列表需要 `updated_at`。

        Returns:
            DTO 列表。
        """
        if not rows:
            return []

        articles = [row[0] for row in rows]
        article_ids = [a.id for a in articles]
        user_ids = list({a.user_id for a in articles})
        category_ids = list({a.type_id for a in articles})

        # 三个批量查询并发不了（同一个 session），但都是单条
        authors = await self._repo.fetch_author_names(user_ids)
        categories = await self._repo.fetch_categories(category_ids)
        tags_map = await self._repo.fetch_tags(article_ids)
        liked_ids = await self._repo.fetch_liked_ids(viewer_id or 0, article_ids)

        items: list[ArticleItem] = []
        for row in rows:
            article, like_count, comment_count = row
            category = categories.get(article.type_id)
            payload = {
                "id": article.id,
                "title": article.title,
                "summary": article.summary or "",
                "cover_url": self._storage.public_url(article.cover_url or ""),
                "status": article.status,
                "views": article.views,
                "like_count": int(like_count),
                "comment_count": int(comment_count),
                "is_liked": article.id in liked_ids,
                # 作者被软删时显示空字符串，前端会显示「已注销用户」之类
                "author_name": authors.get(article.user_id, ""),
                "category": (TaxonomyRef(id=category[0], name=category[1]) if category else None),
                "tags": [
                    TaxonomyRef(id=tid, name=tname) for tid, tname in tags_map.get(article.id, [])
                ],
                "created_at": format_time_z(article.created_at),
            }
            if with_updated_at:
                items.append(
                    AdminArticleItem(**payload, updated_at=format_time_z(article.updated_at))
                )
            else:
                items.append(ArticleItem(**payload))
        return items

    # ============================================================
    # 工具
    # ============================================================

    @staticmethod
    def _parse_tag_ids(raw: str) -> list[int]:
        """解析逗号分隔的标签 ID。

        非法片段直接跳过而不是报错：前端偶尔会传 `1,2,` 这种尾巴带逗号的串，
        为它报 400 不值当。

        Args:
            raw: 原始字符串。

        Returns:
            去重后的 ID 列表。
        """
        if not raw:
            return []
        result: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                result.append(int(part))
        return list(dict.fromkeys(result))

    @staticmethod
    def _can_view_draft(article: Article, viewer: "Viewer | None") -> bool:
        """判断访问者能否看到这篇文章的草稿。

        Args:
            article: 文章。
            viewer: 访问者。

        Returns:
            作者本人或管理员可以看。
        """
        if viewer is None:
            return False
        return viewer.user_id == article.user_id or viewer.is_admin

    def extract_image_keys(self, content: str) -> list[str]:
        """从正文里解析出图片 object key。

        解析失败的 src（比如外链图床）直接跳过，不报错 ——
        用户完全可以在文章里贴别人的图，那些图不该进我们的清理列表。

        Args:
            content: Markdown/HTML 正文。

        Returns:
            去重后的 key 列表。
        """
        keys: list[str] = []
        for src in _IMG_SRC_RE.findall(content):
            try:
                key = self._storage.parse_key(src)
            except BizError:
                logger.debug("跳过无法解析的图片地址：{}", src)
                continue
            if key:
                keys.append(key)
        return list(dict.fromkeys(keys))


class Viewer:
    """访问者上下文。

    单独定义而不是直接用 `CurrentUser`：`ArticleService` 不该依赖
    `app.core.deps`（那是 HTTP 层的东西），service 只认「有 user_id 和 is_admin」。
    """

    __slots__ = ("is_admin", "user_id")

    def __init__(self, user_id: int, is_admin: bool) -> None:
        """初始化。

        Args:
            user_id: 用户 ID。
            is_admin: 是否管理员。
        """
        self.user_id = user_id
        self.is_admin = is_admin
