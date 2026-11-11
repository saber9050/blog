"""文章仓储。

**N+1 优化的核心在这一层**：列表页需要拼 6 张表的数据（文章、作者、分类、
标签、点赞数、评论数），最朴素的写法是「查完文章后逐条查关联」——
一页 10 篇就是 61 条 SQL。这里改成「1 条主查询 + 6 条批量查询」，
与页大小无关。

批量查询的方法都以 `fetch_*` 命名，返回 `dict[article_id, ...]`，
由 service 层组装成 DTO。
"""

from typing import Any

from sqlalchemy import Select, column, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import not_deleted
from app.db.models import Article, ArticleImage, Category, Comment, Like, Tag, TagArticle, User


class ArticleRepository:
    """文章读写。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        self._session = session

    # ============================================================
    # 主查询
    # ============================================================

    def _base_select(self) -> Select:
        """带点赞数 / 评论数的文章查询骨架。

        用两个聚合子查询 LEFT JOIN，而不是在 SELECT 里写相关子查询：
        相关子查询会对每一行执行一次，10 行就是 20 次扫描；
        JOIN 聚合子查询只扫一遍 likes / comments 表。

        Returns:
            可继续链式加 where / order 的 select。
        """
        like_sub = (
            select(Like.article_id.label("article_id"), func.count().label("cnt"))
            .group_by(Like.article_id)
            .subquery()
        )
        # 评论只统计未删的：已删评论在前台是占位，不该计入「N 条评论」
        comment_sub = (
            select(Comment.article_id.label("article_id"), func.count().label("cnt"))
            .where(not_deleted(Comment))
            .group_by(Comment.article_id)
            .subquery()
        )

        return (
            select(
                Article,
                func.coalesce(like_sub.c.cnt, 0).label("like_count"),
                func.coalesce(comment_sub.c.cnt, 0).label("comment_count"),
            )
            .outerjoin(like_sub, like_sub.c.article_id == Article.id)
            .outerjoin(comment_sub, comment_sub.c.article_id == Article.id)
        )

    async def paginate_public(
        self,
        page: int,
        page_size: int,
        sort: str,
        category_id: int | None,
        tag_ids: list[int],
        keyword: str,
    ) -> tuple[list[Any], int]:
        """前台文章列表。

        Args:
            page: 页码。
            page_size: 每页条数（已由 service 截断）。
            sort: `latest` 或 `popular`。
            category_id: 分类筛选。
            tag_ids: 标签 ID 列表，命中任一即匹配。
            keyword: 标题或摘要模糊匹配。

        Returns:
            (查询结果行, 总条数)。每行是 `(Article, like_count, comment_count)`。
        """
        # 前台只看已发布
        conditions = [Article.status == 1, not_deleted(Article)]

        if category_id:
            conditions.append(Article.type_id == category_id)

        if tag_ids:
            # 用 IN 子查询而不是 JOIN：JOIN 会让「一篇文章命中两个标签」变成两行，
            # 分页和 total 都会错
            conditions.append(
                Article.id.in_(select(TagArticle.article_id).where(TagArticle.tag_id.in_(tag_ids)))
            )

        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(or_(Article.title.like(pattern), Article.summary.like(pattern)))

        total = await self._count(Article, conditions)

        stmt = self._base_select().where(*conditions)
        if sort == "popular":
            # 热度公式：点赞 *3 + 浏览 *1 + 评论 *2。
            # 直接引用上面 join 出来的 label，不要再写相关子查询 ——
            # 那样每行都要重扫一次 likes / comments，等于把 N+1 换个地方藏起来
            stmt = stmt.order_by(
                (column("like_count") * 3 + Article.views + column("comment_count") * 2).desc(),
                Article.id.desc(),
            )
        else:
            stmt = stmt.order_by(Article.created_at.desc(), Article.id.desc())

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = list((await self._session.execute(stmt)).all())
        return rows, total

    async def paginate_admin(
        self,
        page: int,
        page_size: int,
        status: int | None,
        category_id: int | None,
        tag_id: int | None,
        keyword: str,
    ) -> tuple[list[Any], int]:
        """后台文章列表。包含草稿，但**不含**已软删的。

        Returns:
            (查询结果行, 总条数)。
        """
        conditions = [not_deleted(Article)]

        if status is not None:
            conditions.append(Article.status == status)
        if category_id:
            conditions.append(Article.type_id == category_id)
        if tag_id:
            conditions.append(
                Article.id.in_(select(TagArticle.article_id).where(TagArticle.tag_id == tag_id))
            )
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(or_(Article.title.like(pattern), Article.summary.like(pattern)))

        total = await self._count(Article, conditions)

        stmt = (
            self._base_select()
            .where(*conditions)
            .order_by(Article.created_at.desc(), Article.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        return rows, total

    async def _count(self, model: type, conditions: list) -> int:
        """按条件数总数。

        Args:
            model: 模型类。
            conditions: where 条件列表。

        Returns:
            行数。
        """
        stmt = select(func.count()).select_from(model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int((await self._session.execute(stmt)).scalar_one())

    async def find_by_id(self, article_id: int) -> tuple[Any, ...] | None:
        """取单篇文章（含点赞数 / 评论数）。

        **不过滤 status**：草稿也能取到 —— 是否放行由 service 判断，
        因为作者和管理员需要能看自己的草稿。

        Args:
            article_id: 文章 ID。

        Returns:
            `(Article, like_count, comment_count)`，不存在返回 None。
        """
        stmt = self._base_select().where(Article.id == article_id, not_deleted(Article))
        row = (await self._session.execute(stmt)).first()
        return tuple(row) if row else None

    async def find_published_id(self, article_id: int) -> int | None:
        """确认文章存在且已发布。点赞时用。"""
        stmt = select(Article.id).where(
            Article.id == article_id, Article.status == 1, not_deleted(Article)
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(value) if value else None

    async def random_published_id(self) -> int | None:
        """随机取一篇已发布文章的 ID。"""
        stmt = (
            select(Article.id)
            .where(Article.status == 1, not_deleted(Article))
            # ORDER BY RAND() 在数据量大时很慢，但当前量级（几十篇）无感；
            # 上万篇后再改成「随机 offset」
            .order_by(func.rand())
            .limit(1)
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(value) if value else None

    async def site_stats(self) -> tuple[int, int, int]:
        """站点统计：文章数、总浏览、总点赞。

        Returns:
            (article_count, total_views, total_likes)。
        """
        stmt = select(
            func.count(Article.id),
            func.coalesce(func.sum(Article.views), 0),
        ).where(Article.status == 1, not_deleted(Article))
        article_count, total_views = (await self._session.execute(stmt)).one()

        like_stmt = select(func.count()).select_from(Like)
        total_likes = int((await self._session.execute(like_stmt)).scalar_one())

        return int(article_count), int(total_views), total_likes

    # ============================================================
    # 批量查询（N+1 优化）
    # ============================================================

    async def fetch_author_names(self, user_ids: list[int]) -> dict[int, str]:
        """批量取作者昵称。

        已软删的用户不在结果里，service 会显示成空字符串。
        """
        if not user_ids:
            return {}
        stmt = select(User.id, User.user_name).where(User.id.in_(user_ids), not_deleted(User))
        return {int(row[0]): str(row[1]) for row in (await self._session.execute(stmt)).all()}

    async def fetch_categories(self, category_ids: list[int]) -> dict[int, tuple[int, str]]:
        """批量取分类 `(id, name)`。"""
        if not category_ids:
            return {}
        stmt = select(Category.id, Category.category_name).where(Category.id.in_(category_ids))
        return {
            int(row[0]): (int(row[0]), str(row[1]))
            for row in (await self._session.execute(stmt)).all()
        }

    async def fetch_tags(self, article_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
        """批量取每篇文章的标签。

        一次 JOIN 查询搞定：`tag_articles` 关联 `tags`，
        再按 article_id 分组塞进字典。

        Args:
            article_ids: 文章 ID 列表。

        Returns:
            `{article_id: [(tag_id, tag_name), ...]}`。无标签的文章不在字典里。
        """
        if not article_ids:
            return {}
        stmt = (
            select(TagArticle.article_id, Tag.id, Tag.tag_name)
            .join(Tag, Tag.id == TagArticle.tag_id)
            .where(TagArticle.article_id.in_(article_ids))
            .order_by(TagArticle.article_id, Tag.id)
        )
        result: dict[int, list[tuple[int, str]]] = {}
        for article_id, tag_id, tag_name in (await self._session.execute(stmt)).all():
            result.setdefault(int(article_id), []).append((int(tag_id), str(tag_name)))
        return result

    async def fetch_liked_ids(self, user_id: int, article_ids: list[int]) -> set[int]:
        """批量查当前用户点过哪些文章。

        Args:
            user_id: 当前用户（游客传 0，直接返回空集）。
            article_ids: 本页文章 ID。

        Returns:
            已点赞的文章 ID 集合。
        """
        if not user_id or not article_ids:
            return set()
        stmt = select(Like.article_id).where(
            Like.user_id == user_id, Like.article_id.in_(article_ids)
        )
        return {int(row[0]) for row in (await self._session.execute(stmt)).all()}

    # ============================================================
    # 写入
    # ============================================================

    async def create(self, article: Article) -> int:
        """插入文章，返回自增 ID。"""
        self._session.add(article)
        await self._session.flush()
        return int(article.id)

    async def update_fields(self, article_id: int, **fields: Any) -> None:
        """局部更新。"""
        if not fields:
            return
        article = await self._session.get(Article, article_id)
        if article is None:
            return
        for key, value in fields.items():
            setattr(article, key, value)
        await self._session.flush()

    async def soft_delete(self, article_id: int) -> None:
        """软删除文章。"""
        article = await self._session.get(Article, article_id)
        if article is not None:
            article.deleted_at = func.now()
            await self._session.flush()

    async def count_by_category(self, category_id: int) -> int:
        """该分类下的文章数（不含软删）。转移分类前用来校验。"""
        stmt = (
            select(func.count())
            .select_from(Article)
            .where(Article.type_id == category_id, not_deleted(Article))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def transfer_category(self, from_id: int, to_id: int) -> int:
        """批量转移分类，返回影响行数。"""
        from sqlalchemy import update as sa_update

        result = await self._session.execute(
            sa_update(Article)
            .where(Article.type_id == from_id, not_deleted(Article))
            .values(type_id=to_id)
        )
        return int(result.rowcount or 0)

    # ---------- 标签关联 ----------

    async def replace_tags(self, article_id: int, tag_ids: list[int]) -> None:
        """用新的标签集合替换旧关联。

        先全删再全插，而不是算差集：一篇文章的标签通常不超过 5 个，
        「全删全插」两条 SQL 就够，算差集反而要查一次再逐条比。
        """
        await self._session.execute(delete(TagArticle).where(TagArticle.article_id == article_id))
        for tag_id in dict.fromkeys(tag_ids):  # 去重且保序
            self._session.add(TagArticle(article_id=article_id, tag_id=tag_id))
        await self._session.flush()

    async def delete_tags_of(self, article_id: int) -> None:
        """删除文章的所有标签关联（删文章时）。"""
        await self._session.execute(delete(TagArticle).where(TagArticle.article_id == article_id))

    async def tag_ids_exist(self, tag_ids: list[int]) -> set[int]:
        """过滤出真实存在的标签 ID，用于校验入参。"""
        if not tag_ids:
            return set()
        stmt = select(Tag.id).where(Tag.id.in_(tag_ids))
        return {int(row[0]) for row in (await self._session.execute(stmt)).all()}

    async def category_exists(self, category_id: int) -> bool:
        """分类是否存在。"""
        stmt = select(exists().where(Category.id == category_id))
        return bool((await self._session.execute(stmt)).scalar())

    # ---------- 点赞 ----------

    async def insert_like(self, article_id: int, user_id: int) -> None:
        """插入点赞记录。

        **不预检查是否存在**：唯一索引会拦重复，捕获 IntegrityError 即可。
        「先查再插」在并发下仍会撞索引，还多一次查询。
        """
        self._session.add(Like(article_id=article_id, user_id=user_id))
        await self._session.flush()

    async def delete_like(self, article_id: int, user_id: int) -> int:
        """删除点赞记录，返回影响行数（0 表示本来就没点过）。"""
        result = await self._session.execute(
            delete(Like).where(Like.article_id == article_id, Like.user_id == user_id)
        )
        return int(result.rowcount or 0)

    # ---------- 文章图片 ----------

    async def list_image_keys(self, article_id: int) -> list[str]:
        """取文章已记录的图片 key。"""
        stmt = select(ArticleImage.url).where(
            ArticleImage.article_id == article_id, ArticleImage.url.is_not(None)
        )
        return [str(row[0]) for row in (await self._session.execute(stmt)).all()]

    async def replace_images(self, article_id: int, keys: list[str]) -> None:
        """覆盖文章的图片记录。"""
        await self._session.execute(
            delete(ArticleImage).where(ArticleImage.article_id == article_id)
        )
        for key in dict.fromkeys(keys):
            self._session.add(ArticleImage(article_id=article_id, url=key))
        await self._session.flush()

    async def delete_images_of(self, article_id: int) -> None:
        """删除文章的图片记录（删文章时）。"""
        await self._session.execute(
            delete(ArticleImage).where(ArticleImage.article_id == article_id)
        )

    async def count_comments(self, article_id: int) -> int:
        """文章的评论数（含已删，与评论列表 total 口径一致）。

        删文章时软删评论用不到这个，但它对「删文章前记录一下删了多少评论」有用。
        """
        stmt = select(func.count()).select_from(Comment).where(Comment.article_id == article_id)
        return int((await self._session.execute(stmt)).scalar_one())
