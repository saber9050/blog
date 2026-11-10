"""评论表。

只有两级：`parent_id` 为空（或 0）是一级评论，有值是对某条一级评论的回复。
不支持多级嵌套 —— 三级以上的树形评论没有前端渲染方案，加了也没人用。
"""

from sqlalchemy import BigInteger, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Comment(Base, TimestampMixin, SoftDeleteMixin):
    """评论 / 回复。

    软删除语义与文章不同：**已删除的评论仍要出现在列表里**，
    前端显示「该评论已被删除」的占位。所以 `deleted_at IS NULL` 这个过滤
    在评论模块不能无脑加，要看场景（见 04-comment/design.md）。

    `content` 用 `TEXT` 而不是 `MEDIUMTEXT`：评论区不该出现两万字长文，
    64 KB 已经远超正常评论的长度。
    """

    __tablename__ = "comments"

    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属文章 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="评论者 ID")
    # 可空：NULL 或 0 都表示一级评论。
    # 建议新数据一律写 NULL，0 只是为了兼容旧库的脏数据。
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="父评论 ID，NULL 表示一级评论"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="评论内容")
    # 回复目标昵称是**快照**：被回复的人后来改名，这里不改。
    # 理由：评论展示的是「我当时回复的是谁」，跟着改名会让历史对话错乱。
    #
    # server_default 必须写成 sa.text("''") 而不是 ""：
    # 后者会在 DDL 里渲染成 `DEFAULT `（空值），MySQL 直接报 1064 语法错误。
    reply_to_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        server_default=text("''"),
        comment="回复目标昵称快照",
    )

    __table_args__ = (
        # 一级评论列表：按文章 + parent_id 过滤，按时间倒序
        Index("ix_comments_article_id_parent_id", "article_id", "parent_id"),
        # 后台按用户筛选
        Index("ix_comments_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Comment id={self.id} article={self.article_id} parent={self.parent_id}>"
