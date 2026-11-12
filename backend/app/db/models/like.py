"""点赞表。

与 Go 版的唯一结构性差异：**加了 `UNIQUE(article_id, user_id)`**。
Go 版靠「先查后插」，并发双击会插两条重复记录，点赞数虚高。
加了唯一索引后，插入逻辑要改成捕获 `IntegrityError` 当作「已点赞」处理。
"""

from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Like(Base, TimestampMixin):
    """文章点赞记录。

    没有软删除：取消点赞就是物理删除。
    """

    __tablename__ = "likes"

    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文章 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户 ID")

    __table_args__ = (
        # 一个用户对一篇文章只能有一条记录。
        # 这个约束比「代码里先查一次」可靠：并发下查与插之间有窗口，
        # 只有数据库约束能真正兜住。
        UniqueConstraint("article_id", "user_id", name="uq_likes_article_id_user_id"),
    )

    def __repr__(self) -> str:
        return f"<Like article={self.article_id} user={self.user_id}>"
