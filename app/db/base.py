"""ORM 基类与公共 Mixin。

所有表的公共约定集中在这里，业务模型只继承、不重复定义：

    class Article(Base, TimestampMixin, SoftDeleteMixin):
        __tablename__ = "articles"
        ...
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

# 索引 / 约束的命名约定。
# 不指定的话 MySQL 会自动取名字（如 `ix_articles_type_id`），
# 而 Alembic 生成迁移时用的是 SQLAlchemy 侧的名字，两边对不上会导致
# 每次 autogenerate 都检测出「索引改名」这种假 diff。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> dict[str, Any]:
        """转成普通字典。

        只用于调试与日志，不要拿它直接当 API 响应 ——
        响应结构由各模块的 Schema 决定，ORM 字段与契约字段并不总是一一对应
        （例如 `password_hash` 绝不能出现在响应里）。
        """
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class TimestampMixin:
    """主键与时间戳。

    时间戳由**数据库**生成（`server_default` / `onupdate`），不经 Python：
    应用服务器与数据库的时钟、时区一旦不一致，用 Python `datetime.now()`
    会出现「刚创建的文章显示昨天」这种问题。

    列类型是 `DATETIME` 而不是 `TIMESTAMP`：
    MySQL 的 `TIMESTAMP` 有 2038 年上限，且会自动做时区转换；
    `DATETIME` 存什么读什么，配合连接参数 `SET time_zone='+08:00'` 更可控。
    """

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class SoftDeleteMixin:
    """软删除标记。

    ⚠️ **SQLAlchemy 不像 GORM 那样自动给查询加 `deleted_at IS NULL`**。
    所有查询必须显式调用 `not_deleted(Model)`，漏一处就会让已删数据「复活」。
    这是重写时最容易出数据事故的地方，没有之一。
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True, comment="删除时间，NULL 表示未删除"
    )


def not_deleted(model: Any) -> ColumnElement[bool]:
    """生成软删除过滤条件。

    用法：

        stmt = select(Article).where(not_deleted(Article))

    Args:
        model: 带 `SoftDeleteMixin` 的模型类。

    Returns:
        可直接放进 `.where()` 的布尔表达式。
    """
    return model.deleted_at.is_(None)
