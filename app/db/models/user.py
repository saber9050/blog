"""用户表。

一个用户既是博客读者，也可能是站点管理员，靠 `role_id` 区分。
"""

from sqlalchemy import SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    """用户。

    唯一索引说明：
    - `user_name` 与 `account` 都是全局唯一
    - MySQL 的 `utf8mb4_0900_ai_ci` 排序规则**不区分大小写**，
      所以 `Admin` 与 `admin` 会被判定为重名 —— 这是预期行为，
      与 2026-10-27 迁移到 PostgreSQL 之前的原始行为一致。
    """

    __tablename__ = "users"

    user_name: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="昵称，业务限 1-15 字符"
    )
    account: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="账号，11 位数字"
    )
    # 列宽 255 是因为 bcrypt 哈希是 60 字符，留出算法升级（换成 argon2）的余量
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 密码哈希"
    )
    email: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="邮箱，可空")
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True, comment="个人简介")
    # 存 object key（如 all/20261109/ab12.jpg），不是完整 URL。
    # 存完整 URL 的话，换域名或换 bucket 要全表 UPDATE。
    avatar_url: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="头像 object key"
    )
    # 用 SmallInteger 而不是 Boolean：MySQL 的 TINYINT(1) 会被驱动映射成 bool，
    # 导致接口返回 true/false 而不是 1/0，前端按数字判断的逻辑会全错
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1", comment="状态：1 启用 / 0 禁用"
    )
    role_id: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", comment="角色：1 管理员 / 0 普通用户"
    )

    def __repr__(self) -> str:
        """调试用表示。不含密码哈希。"""
        return f"<User id={self.id} account={self.account!r} role={self.role_id}>"
