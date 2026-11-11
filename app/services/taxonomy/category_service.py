"""分类业务。

与标签的唯一差异：**删除前要检查有没有文章还在用这个分类**。
直接删会让那些文章的 `type_id` 指向一个不存在的分类，前台按分类筛选时
整批文章消失，而且后台列表里分类列会显示为空。
"""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.db.models import Category
from app.repositories.taxonomy.category_repository import CategoryRepository
from app.services.taxonomy.base import TaxonomyService


class CategoryService(TaxonomyService[Category]):
    """分类。"""

    # `categorys.category_name` 是 VARCHAR(50)
    name_max_length = 50

    def __init__(self, session: AsyncSession, repo: CategoryRepository) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 分类仓储。
        """
        super().__init__(session, repo)
        self._category_repo = repo

    async def _before_delete(self, entity: Category) -> None:
        """删除前检查文章占用。

        只统计**未软删**的文章：已删的文章在列表里根本不出现，
        它们不该阻止分类删除。

        Raises:
            BizError: 400 该分类下存在文章。
        """
        article_count = await self._category_repo.count_articles(entity.id)
        if article_count > 0:
            # 文案严格照文档：前端可能按 message 匹配做提示，
            # 把数量拼进去会破坏这种匹配
            logger.info("拒绝删除分类 id={}，仍有 {} 篇文章", entity.id, article_count)
            raise BizError(ErrorCode.BAD_REQUEST, "该分类下存在文章，无法删除")

    def _not_found_message(self) -> str:
        return "分类不存在"

    def _duplicate_message(self) -> str:
        return "分类名称已存在"

    def _entity_label(self) -> str:
        return "分类"
