"""评论业务。

两条与 Go 版不同的规则（本轮有意修掉的）：

1. **删一级评论会级联软删其回复**。Go 版只删一条，子回复留在库里，
   前台看不见但会继续计入 total、在后台列表里冒出来。
2. **total 与列表口径一致**（都含已删）。Go 版计数不含、列表含，
   导致「total=3 但渲染 5 条」的分页错位。
"""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsFileStorage
from app.core.timefmt import format_time_iso, format_time_z
from app.db.models import Comment
from app.repositories.comment_repository import CommentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.comment import (
    AdminCommentItem,
    AdminCommentQuery,
    CommentCreateRequest,
    CommentItem,
)


class CommentService:
    """评论读写。"""

    # 一级列表：默认 20，上限 50
    TOP_PAGE_SIZE_DEFAULT = 20
    TOP_PAGE_SIZE_MAX = 50
    # 二级列表：默认 10，上限 30（与一级不同，前端已按这个写死）
    REPLY_PAGE_SIZE_DEFAULT = 10
    REPLY_PAGE_SIZE_MAX = 30
    # 后台列表上限
    ADMIN_PAGE_SIZE_MAX = 50

    def __init__(
        self,
        session: AsyncSession,
        repo: CommentRepository,
        user_repo: UserRepository,
        storage: SupportsFileStorage,
        settings: Settings,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 评论仓储。
            user_repo: 用户仓储（校验评论者状态、拼昵称头像）。
            storage: 对象存储（拼头像 URL）。
            settings: 全局配置。
        """
        self._session = session
        self._repo = repo
        self._user_repo = user_repo
        self._storage = storage
        self._settings = settings

    # ============================================================
    # 前台查询
    # ============================================================

    async def list_top_level(self, article_id: int, page: int, page_size: int) -> dict[str, object]:
        """一级评论列表。

        文章不存在也返回空列表，不报 404 —— Go 版行为，前端靠这个
        避免「文章刚删、页面还没刷新」时报错弹窗。

        Returns:
            `{list, total, page, page_size}`。
        """
        page_size = min(page_size, self.TOP_PAGE_SIZE_MAX)
        rows, total = await self._repo.paginate_top_level(article_id, page, page_size)

        # 批量查子回复数，一次 GROUP BY，不按评论逐条查
        parent_ids = [row[0].id for row in rows]
        children = await self._repo.count_children(parent_ids)

        items = [
            self._to_item(comment, user_name, avatar_url, children.get(comment.id, 0))
            for comment, user_name, avatar_url in rows
        ]
        return {"list": items, "total": total, "page": page, "page_size": page_size}

    async def list_replies(
        self, article_id: int, comment_id: int, page: int, page_size: int
    ) -> dict[str, object]:
        """二级回复列表。

        `article_id` 只用于路径一致性，**不做归属校验** ——
        传别的文章 ID 也能查到，这是 Go 版行为，无安全影响（评论本身公开）。

        Returns:
            `{list, total, page, page_size}`，`children_total` 恒为 0。
        """
        page_size = min(page_size, self.REPLY_PAGE_SIZE_MAX)
        rows, total = await self._repo.paginate_replies(comment_id, page, page_size)

        items = [
            self._to_item(comment, user_name, avatar_url, 0)
            for comment, user_name, avatar_url in rows
        ]
        return {"list": items, "total": total, "page": page, "page_size": page_size}

    # ============================================================
    # 发表 / 删除
    # ============================================================

    async def create(self, article_id: int, user_id: int, req: CommentCreateRequest) -> CommentItem:
        """发表评论或回复。

        Raises:
            BizError: 404 用户不存在 / 父评论不存在 / 403 被封禁
                / 400 父评论不属于该文章。
        """
        user = await self._user_repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")
        if user.status == 0:
            raise BizError(ErrorCode.FORBIDDEN, "该用户已被封禁")

        if req.parent_id:
            parent = await self._repo.find_by_id(req.parent_id)
            if parent is None:
                raise BizError(ErrorCode.NOT_FOUND, "资源不存在")
            if parent.article_id != article_id:
                raise BizError(ErrorCode.BAD_REQUEST, "父评论不属于该文章")

        comment = Comment(
            article_id=article_id,
            user_id=user_id,
            parent_id=req.parent_id,
            content=req.content,
            # 昵称快照：被回复的人后来改名，这里不改 ——
            # 评论展示的是「我当时回复的是谁」
            reply_to_name=req.reply_to_user_name or "",
        )
        await self._repo.insert(comment)
        # flush 只拿到自增 id，`created_at` 是数据库的 DEFAULT 生成的，
        # Python 侧还没值。不 refresh 就去读它，会触发一次隐式 SELECT ——
        # 在同步方法里那次 IO 会抛 MissingGreenlet
        await self._session.refresh(comment)
        await self._session.commit()

        logger.info("评论已发表 id={} article={} parent={}", comment.id, article_id, req.parent_id)
        return self._to_item(
            comment,
            user.user_name,
            self._storage.public_url(user.avatar_url or ""),
            0,
        )

    async def delete(self, article_id: int, comment_id: int, user_id: int, is_admin: bool) -> None:
        """删除评论（作者本人或管理员）。

        删一级评论会**级联软删其下所有回复**。

        Raises:
            BizError: 404 评论不存在 / 403 无权限。
        """
        comment = await self._repo.find_by_id(comment_id)
        if comment is None or comment.deleted_at is not None:
            raise BizError(ErrorCode.NOT_FOUND, "资源不存在")

        if not is_admin and comment.user_id != user_id:
            raise BizError(ErrorCode.FORBIDDEN, "禁止访问")

        affected = await self._repo.soft_delete_with_replies(comment_id)
        await self._session.commit()
        logger.info("评论已删除 id={} 连带 {} 条", comment_id, affected)

    # ============================================================
    # 后台
    # ============================================================

    async def admin_list(self, query: AdminCommentQuery) -> dict[str, object]:
        """后台列表。只返回未删除的评论。"""
        page_size = min(query.page_size, self.ADMIN_PAGE_SIZE_MAX)
        rows, total = await self._repo.paginate_admin(
            page=query.page,
            page_size=page_size,
            article_title=query.article_title,
            user_name=query.user_name,
            start_time=query.start_time,
            end_time=query.end_time,
        )
        items = [
            AdminCommentItem(
                id=comment.id,
                article_title=article_title or "",
                user_name=user_name or "",
                content=comment.content,
                # 后台是字符串格式，与前台评论的 isoformat 不同 —— 契约如此
                created_at=format_time_z(comment.created_at),
            )
            for comment, article_title, user_name in rows
        ]
        return {"list": items, "total": total, "page": query.page, "page_size": page_size}

    async def admin_delete(self, comment_id: int) -> None:
        """后台删除单条（同样级联删回复）。

        Raises:
            BizError: 404 评论不存在或已删。
        """
        comment = await self._repo.find_by_id(comment_id)
        if comment is None or comment.deleted_at is not None:
            raise BizError(ErrorCode.NOT_FOUND, "资源不存在")

        affected = await self._repo.soft_delete_with_replies(comment_id)
        await self._session.commit()
        logger.info("后台删除评论 id={} 连带 {} 条", comment_id, affected)

    async def admin_batch_delete(self, ids: list[int]) -> int:
        """批量删除。

        空数组返回 0 不报错；不存在的 ID 自动跳过。

        Returns:
            实际删除条数。
        """
        if not ids:
            return 0
        affected = await self._repo.batch_soft_delete(ids)
        await self._session.commit()
        logger.info("批量删除评论 {} 条", affected)
        return affected

    # ============================================================
    # 组装
    # ============================================================

    def _to_item(
        self,
        comment: Comment,
        user_name: str | None,
        avatar_url: str | None,
        children_total: int,
    ) -> CommentItem:
        """把 ORM 对象转成 DTO。

        已删除的评论**内容清空**：即使库里的 content 还在，
        也不该把它发给前端 —— 否则接口就成了「软删数据泄露通道」。

        Args:
            comment: 评论实体。
            user_name: 评论者昵称（LEFT JOIN 来的，可能为 None）。
            avatar_url: 头像 object key。
            children_total: 子回复数。

        Returns:
            评论 DTO。
        """
        is_deleted = comment.deleted_at is not None
        return CommentItem(
            id=comment.id,
            content="" if is_deleted else comment.content,
            user_id=comment.user_id,
            user_name=user_name or "",
            avatar_url=self._storage.public_url(avatar_url or ""),
            parent_id=comment.parent_id,
            reply_to_name=comment.reply_to_name or "",
            is_deleted=is_deleted,
            # 评论用带时区+微秒的格式，与文章的假 Z 不同
            created_at=format_time_iso(comment.created_at),
            children_total=children_total,
        )
