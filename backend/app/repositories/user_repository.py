"""users 表的资料视角查询。

与 `AuthRepository` 的分工：这里管 `avatar_url` / `introduction` / 后台分页，
认证那边只管账号、密码、状态这类「能不能登录」的字段。
两边都操作 `users` 表，但关注点不重叠 —— 合并会得到一个谁都不敢动的大类。
"""

from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import not_deleted
from app.db.models import User


class UserRepository:
    """用户资料的读写。

    所有查询带 `deleted_at IS NULL`：软删的用户不该出现在列表里，
    也不该占用邮箱。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 请求级数据库会话。
        """
        self._session = session

    async def find_by_id(self, user_id: int) -> User | None:
        """按 ID 查（含软删过滤）。"""
        stmt = select(User).where(User.id == user_id, not_deleted(User))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_email(self, email: str) -> User | None:
        """按邮箱查。"""
        stmt = select(User).where(User.email == email, not_deleted(User))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def exists_email(self, email: str) -> bool:
        """邮箱是否已被占用。"""
        stmt = select(exists().where(User.email == email, not_deleted(User)))
        return bool((await self._session.execute(stmt)).scalar())

    async def exists_account(self, account: str) -> bool:
        """账号是否已被占用。后台创建用户时用。"""
        stmt = select(exists().where(User.account == account, not_deleted(User)))
        return bool((await self._session.execute(stmt)).scalar())

    async def exists_name_excluding(self, user_name: str, exclude_id: int) -> bool:
        """昵称是否被**别人**占用。

        编辑资料时必须排除自己，否则「昵称不改，只改简介」也会报「已存在」。

        Args:
            user_name: 待检测昵称。
            exclude_id: 要排除的用户 ID（通常是当前登录用户）。

        Returns:
            被他人占用返回 True。
        """
        stmt = select(
            exists().where(
                User.user_name == user_name,
                User.id != exclude_id,
                not_deleted(User),
            )
        )
        return bool((await self._session.execute(stmt)).scalar())

    async def update_fields(self, user_id: int, **fields: Any) -> None:
        """局部更新。

        用 `**fields` 而不是传整个对象：整对象更新会把「本次没传的字段」
        也写回去，一旦上层不小心把 None 塞进去就把数据洗掉了。
        空 dict 直接跳过，避免生成 `UPDATE ... SET` 这种非法 SQL。
        """
        if not fields:
            return
        await self._session.execute(update(User).where(User.id == user_id).values(**fields))

    async def paginate(
        self,
        page: int,
        page_size: int,
        keyword: str = "",
        status: int | None = None,
        start_time: str = "",
        end_time: str = "",
    ) -> tuple[list[User], int]:
        """后台分页查询普通用户。

        **只返回 `role_id=0`**：管理员不混在用户列表里，
        否则后台「禁用用户」时容易误操作把自己禁掉。

        Args:
            page: 页码，从 1 开始。
            page_size: 每页条数。
            keyword: 昵称或账号模糊匹配。
            status: 1 启用 / 0 禁用，None 表示不筛。
            start_time: 注册时间起，`YYYY-MM-DD`。
            end_time: 注册时间止，`YYYY-MM-DD`。

        Returns:
            (当前页用户列表, 总条数)。
        """
        conditions = [User.role_id == 0, not_deleted(User)]

        if keyword:
            # 昵称或账号任一命中。用 LIKE 而不是全文索引：数据量小，够用
            pattern = f"%{keyword}%"
            conditions.append(or_(User.user_name.like(pattern), User.account.like(pattern)))

        if status is not None:
            conditions.append(User.status == status)

        if start_time:
            conditions.append(User.created_at >= start_time)

        if end_time:
            # 传日期不带时分秒时，`<= 2026-11-11` 只到当天 00:00:00，
            # 当天的记录会被漏掉。补到 23:59:59 才符合「截止到这天」的直觉
            conditions.append(User.created_at <= f"{end_time} 23:59:59")

        total = (
            await self._session.execute(select(func.count()).select_from(User).where(*conditions))
        ).scalar_one()

        stmt = (
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, int(total)

    async def soft_delete(self, user_id: int) -> None:
        """软删除：写 `deleted_at`。

        不级联删文章与评论 —— 历史内容保留，作者名会显示为空。
        Go 版也是这样，本轮不改。
        """
        await self._session.execute(
            update(User).where(User.id == user_id).values(deleted_at=func.now())
        )
