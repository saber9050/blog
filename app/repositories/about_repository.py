"""关于页仓储。

`abouts` 是单行表：全表只存一条记录，靠代码「取第一行」控制，
没有唯一约束强制。容忍误插的脏数据 —— 真出现两条时永远读最早那条。
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import About


class AboutRepository:
    """关于页读写。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        self._session = session

    async def get_first(self) -> About | None:
        """取关于页记录。

        按 id 正序取第一条：万一历史数据里有重复插入，
        永远读最早那条，行为确定。
        """
        stmt = select(About).order_by(About.id.asc()).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_empty(self) -> About:
        """建一条空记录。

        空表时更新接口要有落点 —— 先建再改，比「UPDATE 影响 0 行后
        再改走 INSERT」简单。

        Returns:
            新建的记录（已 flush，带 id）。
        """
        about = About()
        self._session.add(about)
        await self._session.flush()
        return about

    async def update_fields(self, about_id: int, **fields: Any) -> None:
        """局部更新。"""
        if not fields:
            return
        about = await self._session.get(About, about_id)
        if about is None:
            return
        for key, value in fields.items():
            setattr(about, key, value)
        await self._session.flush()

    async def count(self) -> int:
        """记录数，仅用于日志与自检。"""
        stmt = select(func.count()).select_from(About)
        return int((await self._session.execute(stmt)).scalar_one())
