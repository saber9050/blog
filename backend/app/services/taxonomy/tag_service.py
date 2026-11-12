"""标签业务。

与分类的唯一差异：**标签下有文章也允许删除**。
删除时先把 `tag_articles` 里的关联清掉，文章本身不动，只是少一个标签。
"""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tag
from app.repositories.taxonomy.tag_repository import TagRepository
from app.services.taxonomy.base import TaxonomyService


class TagService(TaxonomyService[Tag]):
    """标签。"""

    # `tags.tag_name` 是 VARCHAR(100)
    name_max_length = 100

    def __init__(self, session: AsyncSession, repo: TagRepository) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 标签仓储。
        """
        super().__init__(session, repo)
        self._tag_repo = repo

    async def _before_delete(self, entity: Tag) -> None:
        """删除前清掉文章关联。

        不清理的话会留下指向不存在标签的孤儿行 —— 文章详情页查标签时
        得到空 list，前端显示「这篇文章没有任何标签」，看起来像数据丢了。

        注意：这里**不阻止删除**。标签是附加信息，用户想删就删，
        文章不该因为少了个标签而删不掉。
        """
        removed = await self._tag_repo.delete_orphan_links(entity.id)
        if removed:
            logger.info("删除标签 id={} 时清理了 {} 条文章关联", entity.id, removed)

    def _not_found_message(self) -> str:
        return "标签不存在"

    def _duplicate_message(self) -> str:
        return "标签名称已存在"

    def _entity_label(self) -> str:
        return "标签"
