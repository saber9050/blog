"""users 表的认证视角查询。

为什么 02-user 还会有一个 `UserRepository`：两者关注点不同。
认证只关心 `account` / `email` / `password_hash` / `status` / `role_id`，
资料模块关心 `avatar_url` / `introduction`。合并会得到一个什么都装的大类，
最后谁都不敢删字段。Go 版也是这么拆的。
"""

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import not_deleted
from app.db.models import User


class AuthRepository:
    """认证相关的用户查询。

    只持有 session，**不管事务边界**：commit / rollback 由 service 决定。
    这样注册这种「写 users 之后可能还要写别的表」的流程才能在一个事务里完成。

    所有查询都带 `deleted_at IS NULL`：软删除的用户不该能登录。
    注意唯一索引是库级别的，被软删的昵称仍然占着 ——
    这个矛盾留给 02-user 处理（恢复或改昵称），认证侧只保证不认它。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 请求级数据库会话。
        """
        self._session = session

    async def find_by_account(self, account: str) -> User | None:
        """按账号查用户。

        Args:
            account: 11 位账号。

        Returns:
            用户对象，不存在返回 None。
        """
        stmt = select(User).where(User.account == account, not_deleted(User))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_email(self, email: str) -> User | None:
        """按邮箱查用户。"""
        stmt = select(User).where(User.email == email, not_deleted(User))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_id(self, user_id: int) -> User | None:
        """按 ID 查用户。刷新令牌时要确认账号没被禁用。"""
        stmt = select(User).where(User.id == user_id, not_deleted(User))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def exists_name(self, user_name: str) -> bool:
        """昵称是否已被占用。

        MySQL 的 ci 排序规则下 `Admin` 与 `admin` 会命中同一条，
        所以这里不需要额外做大小写处理。
        """
        stmt = select(exists().where(User.user_name == user_name, not_deleted(User)))
        return bool((await self._session.execute(stmt)).scalar())

    async def exists_account(self, account: str) -> bool:
        """账号是否已被占用。"""
        stmt = select(exists().where(User.account == account, not_deleted(User)))
        return bool((await self._session.execute(stmt)).scalar())

    async def create(self, user: User) -> int:
        """插入用户。

        MySQL 不支持 `RETURNING`，用 flush 拿自增主键。
        **不 commit**：事务边界归 service。

        Args:
            user: 待插入的用户对象。

        Returns:
            自增主键。
        """
        self._session.add(user)
        await self._session.flush()
        return user.id

    async def update_password(self, user_id: int, password_hash: str) -> None:
        """更新密码哈希。"""
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )
