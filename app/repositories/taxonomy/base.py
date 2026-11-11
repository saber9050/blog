"""分类 / 标签仓储的泛型基类。

两张表结构几乎一样（`id` + 名称 + 状态 + 时间戳），只差表名与名称列名。
复制两份代码意味着「加一个排序规则」要改两处，所以抽基类。

不追求「完全通用的 ORM 抽象」：只覆盖这两个实体真正用到的操作，
多的方法不加 —— 一个泛型基类的方法越多，将来想改就越难。
"""

from typing import Any, Generic, TypeVar

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import Category, Tag

# 只允许这两个模型，避免有人拿它去泛型化别的表
ModelT = TypeVar("ModelT", Category, Tag)


class TaxonomyRepository(Generic[ModelT]):
    """分类 / 标签的公共查询。

    子类只需要在构造时告诉它「用哪个模型、名称列叫什么」，
    其余操作全部复用。
    """

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        name_column: str,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            model: `Category` 或 `Tag`。
            name_column: 名称列的属性名，`category_name` 或 `tag_name`。
        """
        self._session = session
        self._model = model
        self._name_column = name_column

    # ---------- 内部工具 ----------

    @property
    def _name(self) -> Any:
        """名称列的 InstrumentedAttribute。

        用 `getattr` 而不是让子类传列对象：子类构造函数就能保持简单，
        也不用在导入阶段绑定到具体的类。
        """
        return getattr(self._model, self._name_column)

    def name_of(self, entity: ModelT) -> str:
        """取出实体的名称。

        模型上的列名是 `category_name` / `tag_name`，但接口契约统一返回 `name`。
        service 层不应该关心「这次操作的是哪一种」，所以在这里收口。

        Args:
            entity: 分类或标签实体。

        Returns:
            名称字符串。
        """
        return str(getattr(entity, self._name_column) or "")

    # ---------- 查询 ----------

    async def list_enabled(self) -> list[ModelT]:
        """前台列表：只要 `status=1`，按创建时间倒序。

        用 `id` 做次级排序：`created_at` 精度只到秒，同一秒建的多条记录
        排序不稳定，翻页时可能重复或漏掉。加 `id DESC` 就有确定的顺序。
        """
        stmt = (
            select(self._model)
            .where(self._model.status == 1)
            .order_by(self._model.created_at.desc(), self._model.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_enabled(self) -> int:
        """启用数量。"""
        stmt = select(func.count()).select_from(self._model).where(self._model.status == 1)
        return int((await self._session.execute(stmt)).scalar_one())

    async def find_by_id(self, entity_id: int) -> ModelT | None:
        """按 ID 查。"""
        stmt = select(self._model).where(self._model.id == entity_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def exists_name(self, name: str, exclude_id: int = 0) -> bool:
        """名称是否已存在。

        Args:
            name: 名称（已 strip）。
            exclude_id: 更新时排除自己，否则改回原名都会报重复。

        Returns:
            已存在返回 True。
        """
        conditions = [self._name == name]
        if exclude_id:
            conditions.append(self._model.id != exclude_id)
        stmt = select(exists().where(*conditions))
        return bool((await self._session.execute(stmt)).scalar())

    async def paginate(
        self,
        page: int,
        page_size: int,
        status: int | None = None,
        keyword: str = "",
        start_time: str = "",
        end_time: str = "",
    ) -> tuple[list[ModelT], int]:
        """后台分页。

        Returns:
            (当前页数据, 总条数)。
        """
        conditions = []
        if status is not None:
            conditions.append(self._model.status == status)
        if keyword:
            conditions.append(self._name.like(f"%{keyword}%"))
        if start_time:
            conditions.append(self._model.created_at >= start_time)
        if end_time:
            # 补到当天 23:59:59，否则「截止到 11-11」会漏掉当天数据
            conditions.append(self._model.created_at <= f"{end_time} 23:59:59")

        count_stmt = select(func.count()).select_from(self._model)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        stmt = select(self._model)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(self._model.created_at.desc(), self._model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, total

    # ---------- 写入 ----------

    async def create(self, name: str, status: int) -> int:
        """新建，返回自增 ID。

        **不 commit**：事务边界归 service —— 删除标签时要「先清关联再删本体」，
        两步必须在一个事务里。

        Args:
            name: 名称（已 strip）。
            status: 1 启用 / 0 禁用。

        Returns:
            新记录 ID。
        """
        entity = self._model(**{self._name_column: name, "status": status})
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def update(self, entity_id: int, name: str, status: int) -> None:
        """更新名称与状态。"""
        entity = await self.find_by_id(entity_id)
        if entity is None:
            return
        setattr(entity, self._name_column, name)
        entity.status = status
        await self._session.flush()

    async def delete(self, entity_id: int) -> None:
        """物理删除。

        这两张表没有 `deleted_at`，删除是不可逆的 —— 所以分类删除前必须
        由 service 检查「有没有文章在用」。
        """
        entity = await self.find_by_id(entity_id)
        if entity is not None:
            await self._session.delete(entity)
            await self._session.flush()


def model_name(model: type[Base]) -> str:
    """取表名，用于日志。"""
    return getattr(model, "__tablename__", model.__name__)
