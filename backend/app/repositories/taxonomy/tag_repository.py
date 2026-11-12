"""标签仓储。

标签与文章是多对多，删除标签时必须先清 `tag_articles` 里的关联，
否则会留下指向不存在标签的孤儿关联行 —— 文章详情页查标签时得到空 list，
前端会显示成"这篇文章没有任何标签"，看起来像数据丢了。
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tag, TagArticle
from app.repositories.taxonomy.base import TaxonomyRepository


class TagRepository(TaxonomyRepository[Tag]):
    """`tags` 表。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        super().__init__(session, Tag, name_column="tag_name")

    async def delete_orphan_links(self, tag_id: int) -> int:
        """删除该标签的所有文章关联。

        与分类不同：**标签下有文章也允许删除**，只是把标签从文章上摘掉。

        Args:
            tag_id: 标签 ID。

        Returns:
            删掉的关联行数（用于日志，不参与业务判断）。
        """
        result = await self._session.execute(delete(TagArticle).where(TagArticle.tag_id == tag_id))
        return int(result.rowcount or 0)
