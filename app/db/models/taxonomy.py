"""分类与标签。

两张表结构几乎一样（都是「名称 + 启用状态」），但业务规则不同：
- 分类是文章的唯一归属，有文章时不允许删除
- 标签是附加信息，删除时只清理关联，不动文章

表名注意：分类表叫 `categorys`，**少一个 e**。
这是 Go 版本的 `TableName()` 就写成的样子，前端 SQL、旧库、文档里都这么引用，
重写时照抄，不要「顺手修正」——改了就连不上现有表。
"""

from sqlalchemy import BigInteger, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    """文章分类。

    没有 `deleted_at`：删除是物理删除。所以也没有 `SoftDeleteMixin`。
    """

    __tablename__ = "categorys"

    category_name: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="分类名"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1", comment="状态：1 启用 / 0 禁用"
    )

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.category_name!r}>"


class Tag(Base, TimestampMixin):
    """文章标签。同样物理删除。"""

    __tablename__ = "tags"

    tag_name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="标签名"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1", comment="状态：1 启用 / 0 禁用"
    )

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.tag_name!r}>"


class TagArticle(Base, TimestampMixin):
    """文章与标签的多对多关联。

    独立建表而不是用 SQLAlchemy 的 `secondary`：
    - 关联行本身有主键与时间戳，便于排查「这条关联什么时候加的」
    - 删除标签时要能精确 `DELETE WHERE tag_id = ?`，独立模型更直白

    不建物理外键：与 Go 版一致，一致性由代码保证。物理外键会让
    「删文章时连带删关联」变成数据库行为，反而不好在应用层做补偿。
    """

    __tablename__ = "tag_articles"

    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文章 ID")
    tag_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="标签 ID")

    # 联合索引：按文章查标签、按标签查文章都是高频操作
    __table_args__ = (
        Index("ix_tag_articles_article_id", "article_id"),
        Index("ix_tag_articles_tag_id", "tag_id"),
    )
