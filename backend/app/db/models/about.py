"""关于页。

设计上是一张**单行表**：全表只存一条记录，保存站点主人的自我介绍。
没有唯一约束强制单行 —— 靠代码「取第一行」控制，容忍误插的脏数据。

字段名注意：GitHub 地址的列名是 `git_hub`（带下划线），
响应 JSON 也是 `git_hub`，不是 `github`。
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class About(Base, TimestampMixin):
    """关于页内容。

    `tech_stack` / `interest` 是**逗号分隔的字符串**，不是 JSON 数组。
    前端自己 split —— 这是 Go 版的既有契约，本轮不改。
    """

    __tablename__ = "abouts"

    tech_stack: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="技术栈，逗号分隔"
    )
    my_story: Mapped[str | None] = mapped_column(Text, nullable=True, comment="我的故事")
    why: Mapped[str | None] = mapped_column(Text, nullable=True, comment="为什么建立这个博客")
    interest: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="感兴趣的技术方向，逗号分隔"
    )
    git_hub: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="GitHub 地址")
    csdn: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="CSDN 地址")

    def __repr__(self) -> str:
        return f"<About id={self.id}>"
