"""分类仓储。

在泛型基类之上只加一个方法：统计该分类下有多少篇文章。
删除前必须检查 —— 直接删会让文章指向一个不存在的分类，前台列表直接空白。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import not_deleted
from app.db.models import Article, Category
from app.repositories.taxonomy.base import TaxonomyRepository


class CategoryRepository(TaxonomyRepository[Category]):
    """`categorys` 表。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        super().__init__(session, Category, name_column="category_name")

    async def count_articles(self, category_id: int) -> int:
        """该分类下的文章数（不含已软删的）。

        已删的文章不该阻止分类删除 —— 它们在列表里根本不出现。

        Args:
            category_id: 分类 ID。

        Returns:
            文章数量。
        """
        stmt = (
            select(func.count())
            .select_from(Article)
            .where(Article.type_id == category_id, not_deleted(Article))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def delete_orphan_links(self, category_id: int) -> None:
        """占位：分类与文章没有关联表（文章用 `type_id` 直接指向分类）。

        保留这个方法名是为了让「删除前清理」的语义在两个子类里保持一致，
        读代码的人不用去想「为什么分类没有这一步」。
        """
        return None
