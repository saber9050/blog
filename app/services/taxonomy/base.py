"""分类 / 标签的公共业务骨架（模板方法）。

两者 90% 的逻辑一样：strip、查重、CRUD、分页。
剩下的差异（删除前要不要检查文章、要不要先清关联表）通过钩子交给子类。

为什么用模板方法而不是复制两份：将来要加「专题」这类新实体，
实现三个钩子就能复用整套逻辑；复制两份的话，改一处规则要改三遍。
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.timefmt import format_time_z
from app.db.models import Category, Tag
from app.repositories.taxonomy.base import TaxonomyRepository
from app.schemas.taxonomy import (
    TaxonomyCreateRequest,
    TaxonomyQuery,
    TaxonomyUpdateRequest,
)

ModelT = TypeVar("ModelT", Category, Tag)


class TaxonomyService(ABC, Generic[ModelT]):
    """分类 / 标签的公共流程。

    子类只需实现：名称上限、报错文案、删除前的钩子。
    """

    #: 名称最大长度，子类覆盖（分类 50 / 标签 100）
    name_max_length: int = 50

    def __init__(
        self,
        session: AsyncSession,
        repo: TaxonomyRepository[ModelT],
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话（控制事务）。
            repo: 具体实体的仓储。
        """
        self._session = session
        self._repo = repo

    # ============================================================
    # 查询
    # ============================================================

    async def list_public(self) -> list[dict[str, object]]:
        """前台列表：只要启用的，按创建时间倒序。

        Returns:
            `[{"id": 1, "name": "后端"}, ...]` —— 字段名统一是 `name`。
        """
        rows = await self._repo.list_enabled()
        return [{"id": entity.id, "name": self._repo.name_of(entity)} for entity in rows]

    async def count_enabled(self) -> int:
        """启用数量。首页「N 个分类」用。"""
        return await self._repo.count_enabled()

    async def list_admin(self, query: TaxonomyQuery) -> dict[str, object]:
        """后台分页列表。

        Returns:
            `{list, total, page, page_size}`，注意这里的分页键是**下划线**，
            与后台用户列表的驼峰 `pageSize` 不同 —— 两个模块的历史包袱不一样。
        """
        rows, total = await self._repo.paginate(
            page=query.page,
            page_size=query.page_size,
            status=query.status,
            keyword=query.keyword,
            start_time=query.start_time,
            end_time=query.end_time,
        )
        items = [
            {
                "id": entity.id,
                "name": self._repo.name_of(entity),
                "status": entity.status,
                "created_at": format_time_z(entity.created_at),
            }
            for entity in rows
        ]
        return {
            "list": items,
            "total": total,
            "page": query.page,
            "page_size": query.page_size,
        }

    # ============================================================
    # 写入
    # ============================================================

    async def create(self, req: TaxonomyCreateRequest) -> int:
        """新建。

        `strip()` 放在这里而不是 schema：schema 里的 `min_length=1` 拦不住
        「一个空格」，而 strip 之后才知道是不是真的空。

        Raises:
            BizError: 400 名称为空/超长/重复。
        """
        name = self._normalize_name(req.name)

        if await self._repo.exists_name(name):
            raise BizError(ErrorCode.BAD_REQUEST, self._duplicate_message())

        try:
            new_id = await self._repo.create(name, req.status)
            await self._session.commit()
        except IntegrityError as exc:
            # 唯一索引兜底：exists 检查与 insert 之间有窗口，
            # 并发建同名时只有数据库约束能拦住
            await self._session.rollback()
            raise BizError(ErrorCode.BAD_REQUEST, self._duplicate_message()) from exc

        logger.info("{} 已创建 id={} name={}", self._entity_label(), new_id, name)
        return new_id

    async def update(self, entity_id: int, req: TaxonomyUpdateRequest) -> None:
        """更新。

        查重时排除自己，否则「只改状态、名称原样提交」都会报重复。

        Raises:
            BizError: 404 不存在 / 400 名称为空/超长/重复。
        """
        entity = await self._repo.find_by_id(entity_id)
        if entity is None:
            raise BizError(ErrorCode.NOT_FOUND, self._not_found_message())

        name = self._normalize_name(req.name)
        if await self._repo.exists_name(name, exclude_id=entity_id):
            raise BizError(ErrorCode.BAD_REQUEST, self._duplicate_message())

        try:
            await self._repo.update(entity_id, name, req.status)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise BizError(ErrorCode.BAD_REQUEST, self._duplicate_message()) from exc

        logger.info("{} 已更新 id={} name={}", self._entity_label(), entity_id, name)

    async def delete(self, entity_id: int) -> None:
        """删除（模板方法）。

        流程固定：
          1. 查实体（不存在 → 404）
          2. 执行子类的 `_before_delete` 钩子（可能抛异常阻止删除）
          3. 物理删除

        Raises:
            BizError: 404 不存在 / 子类钩子抛出的业务错误。
        """
        entity = await self._repo.find_by_id(entity_id)
        if entity is None:
            raise BizError(ErrorCode.NOT_FOUND, self._not_found_message())

        # 钩子可能抛 BizError 阻止删除，也可能清掉关联数据
        await self._before_delete(entity)

        await self._repo.delete(entity_id)
        await self._session.commit()
        logger.info("{} 已删除 id={}", self._entity_label(), entity_id)

    # ============================================================
    # 子类必须实现
    # ============================================================

    @abstractmethod
    async def _before_delete(self, entity: ModelT) -> None:
        """删除前的钩子。

        分类：有文章就抛 400。
        标签：清掉 `tag_articles` 里的关联。

        Raises:
            BizError: 需要阻止删除时。
        """
        raise NotImplementedError

    @abstractmethod
    def _not_found_message(self) -> str:
        """「不存在」的文案，如「分类不存在」。"""
        raise NotImplementedError

    @abstractmethod
    def _duplicate_message(self) -> str:
        """「名称重复」的文案，如「分类名称已存在」。"""
        raise NotImplementedError

    @abstractmethod
    def _entity_label(self) -> str:
        """日志里用的实体名，如「分类」。"""
        raise NotImplementedError

    # ============================================================
    # 内部工具
    # ============================================================

    def _normalize_name(self, raw: str) -> str:
        """名称归一化：strip + 长度校验。

        Args:
            raw: 原始入参。

        Returns:
            去掉首尾空白的名称。

        Raises:
            BizError: 400 名称为空或超长。
        """
        name = raw.strip()
        if not name:
            raise BizError(ErrorCode.BAD_REQUEST, "请求参数错误")
        if len(name) > self.name_max_length:
            raise BizError(ErrorCode.BAD_REQUEST, "请求参数错误")
        return name
