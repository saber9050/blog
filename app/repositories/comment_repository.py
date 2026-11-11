"""评论仓储。

与前台其他仓储最大的不同：**查询要包含已删除记录**。
已删评论仍要在列表里占位（前端显示「该评论已删除」），
所以这里**不能**无脑加 `not_deleted()`。

⚠️ 计数与列表必须口径一致 —— Go 版在这里有个 bug：计数用 GORM 的
`Model(&Comment{})`（自动加 `deleted_at IS NULL`），列表用 `Table("comments")`
（不加任何过滤），导致「total=3 但渲染出 5 条」。这里两处都不过滤。
"""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import not_deleted
from app.db.models import Article, Comment, User


class CommentRepository:
    """评论读写。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        self._session = session

    # ============================================================
    # 前台查询（含已删）
    # ============================================================

    async def paginate_top_level(
        self, article_id: int, page: int, page_size: int
    ) -> tuple[list[Any], int]:
        """一级评论列表。

        `parent_id IS NULL OR parent_id = 0` —— 旧数据两种都有，
        只判 NULL 会漏掉一部分历史评论。

        Returns:
            (行列表, 总数)。每行是 `(Comment, user_name, avatar_url)`。
            计数与列表用**同样的条件**，都包含已删。
        """
        conditions = [
            Comment.article_id == article_id,
            (Comment.parent_id.is_(None)) | (Comment.parent_id == 0),
        ]
        return await self._paginate(conditions, page, page_size, ascending=False)

    async def paginate_replies(
        self, parent_id: int, page: int, page_size: int
    ) -> tuple[list[Any], int]:
        """二级回复列表。

        与一级列表相反：按时间**正序**（对话顺序，早的在上）。

        Returns:
            (行列表, 总数)。
        """
        conditions = [Comment.parent_id == parent_id]
        return await self._paginate(conditions, page, page_size, ascending=True)

    async def _paginate(
        self, conditions: list, page: int, page_size: int, *, ascending: bool
    ) -> tuple[list[Any], int]:
        """分页查询骨架。

        Args:
            conditions: where 条件。
            page: 页码。
            page_size: 每页条数。
            ascending: 是否按时间正序。

        Returns:
            (行列表, 总数)。
        """
        count_stmt = select(func.count()).select_from(Comment).where(*conditions)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        order = Comment.created_at.asc() if ascending else Comment.created_at.desc()
        stmt = (
            select(Comment, User.user_name, User.avatar_url)
            # LEFT JOIN：评论者被软删时仍要显示评论，只是昵称为空
            .outerjoin(User, User.id == Comment.user_id)
            .where(*conditions)
            .order_by(order, Comment.id.asc() if ascending else Comment.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        return rows, total

    async def count_children(self, parent_ids: list[int]) -> dict[int, int]:
        """批量统计子回复数。

        一次 GROUP BY 搞定，不要按评论逐条查 —— 一页 20 条评论就是 20 次查询。

        Args:
            parent_ids: 一级评论 ID 列表。

        Returns:
            `{parent_id: 子回复数}`。没有回复的不在字典里。
        """
        if not parent_ids:
            return {}
        stmt = (
            select(Comment.parent_id, func.count())
            .where(Comment.parent_id.in_(parent_ids))
            .group_by(Comment.parent_id)
        )
        return {
            int(row[0]): int(row[1])
            for row in (await self._session.execute(stmt)).all()
            if row[0] is not None
        }

    async def find_by_id(self, comment_id: int) -> Comment | None:
        """按 ID 查（含已删，由调用方判断 `deleted_at`）。"""
        stmt = select(Comment).where(Comment.id == comment_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ============================================================
    # 写入
    # ============================================================

    async def insert(self, comment: Comment) -> int:
        """插入评论，返回 ID。"""
        self._session.add(comment)
        await self._session.flush()
        return int(comment.id)

    async def soft_delete_with_replies(self, comment_id: int) -> int:
        """软删一条评论及其所有回复。

        一条 UPDATE 解决（`id = ? OR parent_id = ?`），
        不要先查子 ID 再逐条删 —— 那样是 N+1，而且中间态可能被并发看到。

        Returns:
            影响行数（用于日志）。
        """
        result = await self._session.execute(
            update(Comment)
            .where(
                (Comment.id == comment_id) | (Comment.parent_id == comment_id),
                not_deleted(Comment),
            )
            .values(deleted_at=func.now())
        )
        return int(result.rowcount or 0)

    async def soft_delete_by_article(self, article_id: int) -> int:
        """软删某篇文章下的全部评论。删文章时调用。

        Returns:
            影响行数。
        """
        result = await self._session.execute(
            update(Comment)
            .where(Comment.article_id == article_id, not_deleted(Comment))
            .values(deleted_at=func.now())
        )
        return int(result.rowcount or 0)

    async def batch_soft_delete(self, ids: list[int]) -> int:
        """批量软删。

        Returns:
            实际影响行数。不存在的 ID 自动跳过，不报错。
        """
        if not ids:
            return 0
        result = await self._session.execute(
            update(Comment)
            .where(Comment.id.in_(ids), not_deleted(Comment))
            .values(deleted_at=func.now())
        )
        return int(result.rowcount or 0)

    # ============================================================
    # 后台查询（只含未删）
    # ============================================================

    async def paginate_admin(
        self,
        page: int,
        page_size: int,
        article_title: str = "",
        user_name: str = "",
        start_time: str = "",
        end_time: str = "",
    ) -> tuple[list[Any], int]:
        """后台评论列表。**只返回未删除的**（与前台相反）。

        Returns:
            (行列表, 总数)。每行是 `(Comment, article_title, user_name)`。
        """
        conditions = [not_deleted(Comment)]
        if article_title:
            conditions.append(Article.title.like(f"%{article_title}%"))
        if user_name:
            conditions.append(User.user_name.like(f"%{user_name}%"))
        if start_time:
            conditions.append(Comment.created_at >= start_time)
        if end_time:
            # 补到 23:59:59，否则当天数据被漏掉
            conditions.append(Comment.created_at <= f"{end_time} 23:59:59")

        # 计数也要带 join：按标题/昵称筛选时，不 join 就找不到对应列，
        # 或者 total 会明显偏大
        count_stmt = (
            select(func.count())
            .select_from(Comment)
            .outerjoin(Article, Article.id == Comment.article_id)
            .outerjoin(User, User.id == Comment.user_id)
            .where(*conditions)
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())

        stmt = (
            select(Comment, Article.title, User.user_name)
            .outerjoin(Article, Article.id == Comment.article_id)
            .outerjoin(User, User.id == Comment.user_id)
            .where(*conditions)
            .order_by(Comment.created_at.desc(), Comment.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        return rows, total
