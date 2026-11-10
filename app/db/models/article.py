"""文章与文章图片引用。

与 Go 版的差异：**没有 4 个 `vector_*` 列**。
向量化功能整体删除后，这些列没有任何消费者，新库不建。
"""

from sqlalchemy import BigInteger, Index, SmallInteger, String
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Article(Base, TimestampMixin, SoftDeleteMixin):
    """文章。

    正文列类型是 `MEDIUMTEXT`（16 MB）而不是 `TEXT`（64 KB）：
    MySQL 的 `TEXT` 上限约 2 万汉字，技术长文很容易超，
    而且**超了不报错、直接截断**，是最难排查的一类数据丢失。

    这里直接用 `mysql.MEDIUMTEXT`，没有用 `Text().with_variant(...)`：
    项目只跑 MySQL，variant 带来的是「Alembic 识别不了实际类型、
    迁移里退化成 TEXT」这种坑，不值当。
    """

    __tablename__ = "articles"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="作者 ID")
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="标题")
    content: Mapped[str] = mapped_column(
        MEDIUMTEXT(),
        nullable=False,
        comment="Markdown 正文",
    )
    # 存 object key，不是完整 URL，理由同 users.avatar_url
    cover_url: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="封面图 object key"
    )
    # 255 是硬上限：AI 生成的摘要超长会被截断后再入库，不能依赖数据库报错
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="摘要")
    views: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", comment="浏览量"
    )
    type_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="分类 ID")
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", comment="状态：1 已发布 / 0 草稿"
    )

    __table_args__ = (
        # 前台列表：按分类筛选 + 只看已发布
        Index("ix_articles_type_id_status", "type_id", "status"),
        # 前台默认排序：已发布 + 按创建时间倒序
        Index("ix_articles_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Article id={self.id} title={self.title!r} status={self.status}>"


class ArticleImage(Base, TimestampMixin):
    """正文里引用的图片。

    这张表**不是**用来渲染页面的（正文里的图片是 Markdown 里的 URL），
    它的唯一用途是：删文章时知道要去 MinIO 删哪些对象。

    没有 `deleted_at`：删文章时这些记录直接物理删除。
    """

    __tablename__ = "article_images"

    article_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="文章 ID"
    )
    url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="图片 object key")

    def __repr__(self) -> str:
        return f"<ArticleImage article_id={self.article_id} key={self.url!r}>"
